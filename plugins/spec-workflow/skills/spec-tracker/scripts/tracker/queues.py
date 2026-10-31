"""Review, test, and merge queues (implementation/queues.json, worktree mode).

An item waits, is granted a slot of its resource class (the parent may brief or resume its agent), holds it once an agent
claims the role's assignment, and leaves the queue when the record leaves the role (handoff). A lease frees the slot of
a dead agent. Review and test items follow the records (`ready_for_review`, `ready_for_test`, `ready_for_retest`); merge
items are added by the parent after the acceptance gate."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import paths as lanes
from . import plan as plans
from .model import now
from .store import TrackerError, load_all, write_atomic

Record = dict[str, Any]
PATH = "implementation/queues.json"
QUEUES = ("review", "test", "merge")
ROLE_QUEUE = {"reviewer": "review", "tester": "test"}
QUEUE_ROLE = {"review": "reviewer", "test": "tester", "merge": "parent"}
TAKEN = ("granted", "holding", "running")
RETEST_PRIORITY = 1


def parse(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def empty() -> Record:
    return {"schema_version": 1, "managed_by": "spec_tracker.py", "queues": {queue: {"items": []} for queue in QUEUES}}


def load(root: Path) -> Record:
    path = root / PATH
    if not path.is_file():
        return empty()
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise TrackerError(f"cannot read {PATH}: {error}") from error
    if not isinstance(state, dict) or state.get("schema_version") != 1:
        raise TrackerError(f"unsupported or malformed {PATH}")
    for queue in QUEUES:
        state["queues"].setdefault(queue, {"items": []})
    return state


def save(root: Path, state: Record) -> None:
    (root / PATH).parent.mkdir(parents=True, exist_ok=True)
    write_atomic(root / PATH, json.dumps(state, indent=2, sort_keys=True) + "\n")


def ordered(items: list[Record]) -> list[Record]:
    return sorted(items, key=lambda item: (-int(item.get("priority", 0)), item["since"]))


def find(state: Record, queue: str, feature: str) -> Record | None:
    return next((item for item in state["queues"][queue]["items"] if item["feature"] == feature), None)


def wanted(queue: str, record: Record) -> bool:
    """Whether the record belongs in the queue now (items of records that left the role drop out)."""
    role = QUEUE_ROLE[queue]
    return record["current_role"] == role and (queue == "merge" or record["status"] in (
        ("ready_for_review",) if queue == "review" else ("ready_for_test", "ready_for_retest")))


def claim_time(root: Path, assignment: str) -> str | None:
    """When an agent claimed the assignment: the hook's marker file (implementation/.assignments/<agent>)."""
    directory = root / lanes.ASSIGNMENTS_DIR
    times = []
    for path in directory.glob("*") if directory.is_dir() else []:
        try:
            if path.read_text(encoding="utf-8").strip() == assignment:
                times.append(path.stat().st_mtime)
        except OSError:
            continue
    return stamp(datetime.fromtimestamp(max(times), timezone.utc)) if times else None


def holder(root: Path, record: Record, role: str, item: Record) -> tuple[str, str] | None:
    """The role's active assignment an agent claimed after the item was queued (a resumed agent keeps its earlier claim
    and holds the slot through the grant)."""
    for lane in reversed(record.get("assignments", [])):
        if lane["status"] == "active" and lane["role"] == role and lane["id"] not in item.get("expired", []):
            claimed = claim_time(root, lane["id"])
            if claimed and parse(claimed) >= parse(item["since"]):
                return lane["id"], claimed
    return None


def lane_class(record: Record, role: str) -> str | None:
    return next((lane.get("slot_class") for lane in reversed(record.get("assignments", []))
                 if lane["status"] == "active" and lane["role"] == role and lane.get("slot_class")), None)


def new_item(feature: str, queue_class: str, priority: int, timestamp: str) -> Record:
    return {"feature": feature, "class": queue_class, "priority": priority, "since": timestamp, "state": "waiting"}


def enqueue(state: Record, queue: str, feature: str, queue_class: str, priority: int, timestamp: str) -> Record:
    item = find(state, queue, feature)
    if item is None:
        item = new_item(feature, queue_class, priority, timestamp)
        state["queues"][queue]["items"].append(item)
    return item


def expire(item: Record, config: Record, moment: datetime) -> bool:
    started = item.get("claimed_at") or item.get("started_at") or item.get("granted_at")
    if item["state"] not in TAKEN or not started or (moment - parse(started)).total_seconds() < config["lease"]:
        return False
    # A dead agent's slot frees; the item goes to the back of its priority band and its old assignment no longer holds.
    item.setdefault("expired", []).extend([item["assignment"]] if item.get("assignment") else [])
    item.setdefault("lease_expired", []).append({"state": item["state"], "since": started, "at": stamp(moment)})
    for key in ("assignment", "claimed_at", "granted_at", "started_at"):
        item.pop(key, None)
    item.update(state="waiting", since=stamp(moment))
    return True


def sync(root: Path, config: Record, records: list[Record] | None = None) -> Record:
    """Bring the queues in line with the records: enqueue, drop, mark holders, expire leases, and grant free slots."""
    state = load(root)
    before = json.dumps(state, sort_keys=True)
    timestamp = now()
    moment = parse(timestamp)
    found = {record["feature"]: record for record in (records if records is not None else load_all(root))}
    for queue in QUEUES:
        role, slots = QUEUE_ROLE[queue], config["slots"][queue]
        items = [item for item in state["queues"][queue]["items"] if item["feature"] in found and wanted(queue, found[item["feature"]])]
        state["queues"][queue]["items"] = items
        if queue != "merge":
            for record in found.values():
                if wanted(queue, record) and find(state, queue, record["feature"]) is None:
                    priority = RETEST_PRIORITY if record["status"] == "ready_for_retest" else 0
                    items.append(new_item(record["feature"], "", priority, timestamp))
        for item in items:
            record = found[item["feature"]]
            if queue != "merge":
                item["class"] = lane_class(record, role) or item.get("class") or ""
                held = holder(root, record, role, item)
                if held and item.get("assignment") != held[0]:
                    item.update(state="holding", assignment=held[0], claimed_at=held[1])
                elif not held and item["state"] == "holding":
                    item.update(state="granted" if item.get("granted_at") else "waiting")
                    item.pop("assignment", None)
                    item.pop("claimed_at", None)
            if item["class"] not in slots:
                item["class"] = "default" if "default" in slots else next(iter(slots))
            expire(item, config, moment)
        used = {name: sum(item["state"] in TAKEN and item["class"] == name for item in items) for name in slots}
        for item in ordered(items):
            blocked = (found[item["feature"]].get("pr") or {}).get("blocking") if queue != "merge" else None
            if item["state"] == "waiting" and not blocked and used[item["class"]] < slots[item["class"]]:
                item.update(state="granted", granted_at=timestamp)
                used[item["class"]] += 1
    if json.dumps(state, sort_keys=True) != before:
        save(root, state)
    return state


def positions(items: list[Record]) -> dict[str, int]:
    """Holders are at position 0; waiting items count from 1 in queue order."""
    waiting = [item for item in ordered(items) if item["state"] not in TAKEN]
    return {**{item["feature"]: 0 for item in items if item["state"] in TAKEN}, **{item["feature"]: index for index, item in enumerate(waiting, 1)}}


def placement(state: Record, feature: str) -> Record:
    for queue in QUEUES:
        items = state["queues"][queue]["items"]
        if find(state, queue, feature):
            return {"name": queue, "position": positions(items)[feature]}
    return {"name": None, "position": None}


def view(state: Record, config: Record, records: list[Record], root: Path) -> Record:
    queues: Record = {}
    found = {record["feature"]: record for record in records}
    for queue in QUEUES:
        items = state["queues"][queue]["items"]
        where = positions(items)
        holders = [{"feature": item["feature"], "class": item["class"], "since": item.get("claimed_at") or item.get("started_at") or item.get("granted_at"),
                    "assignment": item.get("assignment"), "state": item["state"]} for item in items if item["state"] in TAKEN]
        waiting = [{"feature": item["feature"], "class": item["class"], "since": item["since"], "position": where[item["feature"]],
                    "priority": item.get("priority", 0),
                    **({"blocked": (found[item["feature"]].get("pr") or {}).get("blocking")}
                       if item["feature"] in found and (found[item["feature"]].get("pr") or {}).get("blocking") and queue != "merge" else {})}
                   for item in ordered(items) if item["state"] not in TAKEN]
        queues[queue] = {"slots": dict(config["slots"][queue]), "holders": holders, "waiting": waiting}
        if queue == "merge":
            queues[queue]["last"] = state["queues"]["merge"].get("last")
    return {"queues": queues, "agents": agents(root, records)}


def agents(root: Path, records: list[Record]) -> list[Record]:
    running = []
    for record in records:
        total = len((plans.latest(record) or {}).get("batches") or [])
        for lane in record.get("assignments", []):
            claimed = claim_time(root, lane["id"]) if lane["status"] == "active" else None
            if claimed:
                running.append({"assignment": lane["id"], "feature": record["feature"], "role": lane["role"], "model": lane.get("model"),
                                "batch": f"{lane['batch']}/{total}" if lane.get("batch") and total else None, "claimed_at": claimed})
    return running


def ready(state: Record, queue: str, feature: str | None) -> Record | None:
    """The caller's item once it has a slot: the feature's item, else the first granted item nobody has claimed yet."""
    items = state["queues"][queue]["items"]
    if feature:
        item = find(state, queue, feature)
        return item if item and item["state"] in TAKEN else None
    return next((item for item in ordered(items) if item["state"] == "granted"), None)
