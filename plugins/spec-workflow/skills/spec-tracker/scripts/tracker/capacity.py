"""Dynamic slots: an `auto` slot class grants another slot only while the machine has room for one more run.

    "slots": {"test": {"stack": {"auto": true, "min": 1, "max": 3, "memory": "4G", "cpus": 2}, "browser": 2}},
    "capacity": {"reserve_memory": "2G", "reserve_cpus": 1, "warmup": "3m"}

A class's runs already in progress show up in the machine's free memory and load, so the next grant fits on what is
left after the reserve. A run granted within `warmup` may not have started its stack yet, so its declared cost is
taken off as well. Granted slots are never revoked; `min` always holds and `max` caps. `SPEC_WORKFLOW_MACHINE`
(JSON: mem_available_mb, mem_total_mb, cpus, load) replaces the machine reading, for tests and for remote hosts."""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

Record = dict[str, Any]
MEMINFO = "/proc/meminfo"


def machine() -> Record:
    """Free memory (MB), total memory, cores, and the 1-minute load average; None for what this OS can't tell."""
    override = os.environ.get("SPEC_WORKFLOW_MACHINE")
    if override:
        return {"mem_available_mb": None, "mem_total_mb": None, "cpus": None, "load": None, **json.loads(override)}
    found: Record = {"mem_available_mb": None, "mem_total_mb": None, "cpus": os.cpu_count(), "load": None}
    try:
        with open(MEMINFO, encoding="utf-8") as stream:
            fields = {line.split(":")[0]: int(line.split()[1]) for line in stream if line.split()[1:2] and line.split()[1].isdigit()}
        found.update(mem_available_mb=fields.get("MemAvailable", 0) // 1024, mem_total_mb=fields.get("MemTotal", 0) // 1024)
    except OSError:
        pass
    try:
        found["load"] = round(os.getloadavg()[0], 2)
    except OSError:
        pass
    return found


def recent(items: list[Record], holds: list[Record], name: str, moment: datetime, warmup: float, parse: Any) -> int:
    """Grants and holds of the class younger than the warm-up: their stacks may not be using memory yet."""
    stamps = [item.get("granted_at") for item in items if item["class"] == name and item["state"] in ("granted", "holding", "running")]
    stamps += [hold.get("since") for hold in holds if hold["class"] == name]
    return sum(1 for stamp in stamps if stamp and (moment - parse(stamp)).total_seconds() < warmup)


def room(config: Record, queue: str, name: str, warming: int, reading: Record | None = None) -> Record:
    """How many more runs of an auto class fit now, and what limits it; None for a fixed class."""
    need = config.get("auto_slots", {}).get(queue, {}).get(name)
    if need is None:
        return {"auto": False, "extra": None}
    reading = reading or machine()
    reserve = config["capacity"]
    fits, limits = [], []
    if need["memory_mb"] and reading.get("mem_available_mb") is not None:
        spare = reading["mem_available_mb"] - reserve["reserve_memory_mb"] - warming * need["memory_mb"]
        fits.append(spare // need["memory_mb"])
        limits.append(("memory", spare // need["memory_mb"], f"{reading['mem_available_mb']} MB free, {reserve['reserve_memory_mb']} MB reserved"))
    if need["cpus"] and reading.get("cpus") and reading.get("load") is not None:
        spare_cpu = reading["cpus"] - reading["load"] - reserve["reserve_cpus"] - warming * need["cpus"]
        fits.append(int(spare_cpu // need["cpus"]))
        limits.append(("cpu", int(spare_cpu // need["cpus"]), f"load {reading['load']} on {reading['cpus']} cores, {reserve['reserve_cpus']} reserved"))
    if not fits:
        return {"auto": True, "extra": None, "limit": "unknown: this machine reports neither memory nor load; max applies"}
    extra = max(0, int(min(fits)))
    tight = min(limits, key=lambda item: item[1])
    return {"auto": True, "extra": extra, "limit": f"{tight[0]} ({tight[2]})", "warming": warming, "need": need}


def allowed(config: Record, queue: str, name: str, used: int, extra: int | None) -> bool:
    """Whether one more slot of the class may be granted (used counts every slot taken now)."""
    cap = config["slots"][queue][name]
    if used >= cap:
        return False
    need = config.get("auto_slots", {}).get(queue, {}).get(name)
    if need is None or extra is None:
        return True
    return used < need["min"] or extra > 0
