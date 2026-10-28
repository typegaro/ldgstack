"""The project test toolkit manifest (implementation/toolkit.json): durable, project-owned test tools."""
from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path, PurePosixPath
from typing import Any

from .store import TrackerError, write_atomic

SCHEMA_VERSION = 1
CAPABILITIES = (
    "be.inspect", "be.seed", "be.fault", "be.concurrency",
    "fe.drive", "fe.inspect", "fe.audit", "env.isolate", "data.cleanup", "test.runner",
)
MOCK = re.compile(r"^ext\.mock\.[a-z0-9][a-z0-9-]*$")
NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")
MODES = ("read-only", "mutating")
FORBIDDEN_LOCATIONS = ("specs", "implementation")
SMOKE_TIMEOUT = 300
OUTPUT_TAIL = 400


def path(root: Path) -> Path:
    return root / "implementation" / "toolkit.json"


def load(root: Path) -> dict[str, Any]:
    file = path(root)
    if not file.is_file():
        return {"schema_version": SCHEMA_VERSION, "managed_by": "spec_tracker.py", "tools": []}
    try:
        value = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TrackerError(f"cannot read implementation/toolkit.json: {error}") from error
    if not isinstance(value, dict) or value.get("schema_version") != SCHEMA_VERSION or not isinstance(value.get("tools"), list):
        raise TrackerError("unsupported or malformed implementation/toolkit.json")
    return value


def save(root: Path, manifest: dict[str, Any]) -> None:
    manifest["tools"].sort(key=lambda item: item["name"])
    path(root).parent.mkdir(parents=True, exist_ok=True)
    write_atomic(path(root), json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def capability(value: str) -> str:
    if value in CAPABILITIES or MOCK.match(value):
        return value
    raise TrackerError(f"unknown capability {value!r}; use one of {', '.join(CAPABILITIES)}, or ext.mock.<service>")


def provides(tool: dict[str, Any], wanted: str) -> bool:
    """A tool provides `ext.mock` when it has any `ext.mock.<service>`; otherwise capabilities match exactly."""
    return any(item == wanted or item.startswith(wanted + ".") for item in tool["capabilities"])


def location(root: Path, value: str) -> str:
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise TrackerError(f"location must be a relative path inside the project: {value}")
    if relative.parts[0] in FORBIDDEN_LOCATIONS:
        raise TrackerError(f"toolkit tools may not live under {relative.parts[0]}/")
    if not (root / relative).exists():
        raise TrackerError(f"location does not exist yet; build the tool first: {value}")
    return relative.as_posix()


def find(manifest: dict[str, Any], name: str) -> dict[str, Any]:
    for tool in manifest["tools"]:
        if tool["name"] == name:
            return tool
    raise TrackerError(f"unknown toolkit tool: {name}")


def stale(tool: dict[str, Any]) -> bool:
    """Never verified, last smoke failed, or changed since the last passing smoke run."""
    return tool.get("verified_result") != "passed" or tool.get("verified_at", "") < tool.get("updated_at", "")


def view(tool: dict[str, Any]) -> dict[str, Any]:
    return {**tool, "stale": stale(tool)}


def listing(root: Path, wanted: str | None) -> list[dict[str, Any]]:
    tools = load(root)["tools"]
    return [view(tool) for tool in tools if wanted is None or provides(tool, wanted)]


def apply(root: Path, tool: dict[str, Any], args: Any) -> None:
    if args.capability:
        tool["capabilities"] = sorted({capability(item) for item in args.capability})
    # --command is parsed as `entry`: argparse already uses `command` for the subcommand name.
    for field, attribute in (("command", "entry"), ("smoke", "smoke"), ("owner_spec", "owner_spec"), ("description", "description"), ("guard", "guard")):
        value = getattr(args, attribute, None)
        if value is not None:
            tool[field] = value
    if args.location is not None:
        tool["location"] = location(root, args.location)
    if args.mode is not None:
        tool["mode"] = args.mode
    if tool.get("mode") == "mutating" and not tool.get("guard"):
        raise TrackerError("a mutating tool needs --guard: how it refuses the dev database and shared data unless explicitly targeted")


def add(root: Path, args: Any, timestamp: str) -> dict[str, Any]:
    if not NAME.match(args.name):
        raise TrackerError("tool name must be lowercase kebab-case")
    manifest = load(root)
    if any(tool["name"] == args.name for tool in manifest["tools"]):
        raise TrackerError(f"toolkit tool already exists: {args.name}; use toolkit update")
    tool: dict[str, Any] = {"name": args.name, "added_at": timestamp, "updated_at": timestamp, "verified_at": "", "verified_result": ""}
    apply(root, tool, args)
    manifest["tools"].append(tool)
    save(root, manifest)
    return view(tool)


def update(root: Path, args: Any, timestamp: str) -> dict[str, Any]:
    manifest = load(root)
    tool = find(manifest, args.name)
    apply(root, tool, args)
    tool["updated_at"] = timestamp
    save(root, manifest)
    return view(tool)


def remove(root: Path, args: Any) -> dict[str, Any]:
    manifest = load(root)
    find(manifest, args.name)
    manifest["tools"] = [tool for tool in manifest["tools"] if tool["name"] != args.name]
    manifest.setdefault("removed", []).append({"name": args.name, "reason": args.reason})
    save(root, manifest)
    return {"name": args.name, "removed": True}


def verify(root: Path, names: list[str], timeout: int, timestamp: str) -> dict[str, Any]:
    """Run smoke commands from the project root. Stores only the result, never the output (it may hold secrets)."""
    manifest = load(root)
    chosen = [find(manifest, name) for name in names] if names else list(manifest["tools"])
    results = []
    for tool in chosen:
        started = time.monotonic()
        try:
            process = subprocess.run(tool["smoke"], shell=True, cwd=root, capture_output=True, text=True, timeout=timeout)
            passed, output = process.returncode == 0, (process.stdout + process.stderr).strip()
        except subprocess.TimeoutExpired:
            passed, output = False, f"timed out after {timeout}s"
        tool.update(verified_at=timestamp, verified_result="passed" if passed else "failed")
        entry = {"name": tool["name"], "passed": passed, "seconds": round(time.monotonic() - started, 1)}
        if not passed:
            entry["output_tail"] = output[-OUTPUT_TAIL:]
        results.append(entry)
    save(root, manifest)
    failed = [item["name"] for item in results if not item["passed"]]
    return {"verified": len(results), "failed": failed, "results": results}


def summary(root: Path) -> dict[str, Any]:
    """One compact line per tool for delegation prompts."""
    tools = load(root)["tools"]
    return {
        "tools": len(tools),
        "stale": sorted(tool["name"] for tool in tools if stale(tool)),
        "lines": [f"{tool['name']} [{', '.join(tool['capabilities'])}] {tool.get('mode', '?')}: {tool['command']}" for tool in tools],
    }
