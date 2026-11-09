"""Supervision: agents that stopped making progress (`stuck`), and the program's decision log (`decision`).

An agent is judged by its side effects (a claim, a record write, a commit on its branch), never by its status text.
Each role's stuck-after time comes from how long that role's past assignments ran, so a slow role is not flagged early.
The decision log (implementation/decisions.jsonl) is append-only: one row per decision the parent made alone, and a
`waiting` row for each call only the user can make, resolved later by a row that names it."""
from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import queues, workspace
from .model import next_id, now
from .store import TrackerError, load, load_all, project_lock, records_dir, write_atomic

Record = dict[str, Any]
FLOOR = 20 * 60
DEFAULT = 45 * 60
SAMPLES = 3
DECISIONS = Path("implementation/decisions.jsonl")
WRITERS = {"implementer", "fixer", "toolsmith"}


def parse(stamp: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None


def all_records(root: Path) -> list[Record]:
    archived = [load(root, path.stem, archived=True) for path in sorted(records_dir(root, archived=True).glob("*.json"))]
    return load_all(root) + archived


def runtimes(records: list[Record]) -> dict[str, list[float]]:
    found: dict[str, list[float]] = {}
    for record in records:
        for lane in record.get("assignments", []):
            start, end = parse(lane.get("at")), parse(lane.get("released_at"))
            if start and end and end > start:
                found.setdefault(lane["role"], []).append((end - start).total_seconds())
    return found


def threshold(samples: list[float]) -> float:
    return max(FLOOR, 2 * statistics.median(samples)) if len(samples) >= SAMPLES else DEFAULT


def commit_time(root: Path, record: Record) -> str | None:
    tree = record.get("worktree")
    config = workspace.load(root) if tree else None
    if not tree or not config or tree.get("removed_at"):
        return None
    stamps = []
    for repo in tree["repos"]:
        try:
            stamps.append(workspace.git(root / repo / config["main"], "log", "-1", "--format=%cI", tree["branch"]).stdout.strip())
        except Exception:  # noqa: BLE001 (a missing checkout just gives no signal)
            continue
    return max(filter(None, stamps), default=None)


def stuck(root: Path, role: str | None = None) -> Record:
    records = all_records(root)
    limits = {name: threshold(samples) for name, samples in runtimes(records).items()}
    current = datetime.now(timezone.utc)
    rows = []
    for record in (item for item in records if item.get("status") != "accepted"):
        commit = commit_time(root, record)
        for lane in record.get("assignments", []):
            if lane.get("status") != "active" or (role and lane["role"] != role):
                continue
            signals = {"assigned": lane.get("at"), "claimed": queues.claim_time(root, lane["id"]), "record write": record.get("updated_at")}
            if lane["role"] in WRITERS:
                signals["commit"] = commit
            dated = [(name, stamp) for name, value in signals.items() if (stamp := parse(value)) is not None]
            name, last = max(dated, key=lambda item: item[1]) if dated else ("assigned", current)
            idle = (current - last).total_seconds()
            limit = limits.get(lane["role"], DEFAULT)
            rows.append({"feature": record["feature"], "assignment": lane["id"], "role": lane["role"], "claimed": bool(signals["claimed"]),
                         "idle_seconds": round(idle), "stuck_after_seconds": round(limit), "last_signal": name, "stuck": idle > limit})
    flagged = [row for row in rows if row["stuck"]]
    return {"stuck": flagged, "active": rows, "rule": "probe each stuck agent by its side effects; replace it at once by cause: a smaller "
            "scope after a context limit, the same brief after a dropped connection, another model after a tool error; after two "
            "retries drop the unit and replan around it"}


def read(root: Path) -> list[Record]:
    path = root / DECISIONS
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def append(root: Path, row: Record) -> Record:
    with project_lock(root):
        rows = read(root)
        row = {"id": next_id(rows, "D-"), "at": now(), **row}
        path = root / DECISIONS
        path.parent.mkdir(parents=True, exist_ok=True)
        write_atomic(path, "".join(json.dumps(item, separators=(",", ":")) + "\n" for item in rows + [row]))
    return row


def waiting(rows: list[Record]) -> list[Record]:
    answered = {row.get("resolves") for row in rows}
    return [row for row in rows if row.get("waiting") and row["id"] not in answered]


def decision(root: Path, args: Any) -> Any:
    if args.action == "list":
        rows = read(root)
        if args.feature:
            rows = [row for row in rows if row.get("feature") == args.feature]
        return {"waiting": waiting(read(root)), "decisions": rows if not args.waiting else waiting(rows)}
    if args.action == "resolve":
        target = next((row for row in read(root) if row["id"] == args.id), None)
        if target is None or not target.get("waiting"):
            raise TrackerError(f"{args.id} is not a call waiting on the user")
        if target["id"] not in {row["id"] for row in waiting(read(root))}:
            raise TrackerError(f"{args.id} is already resolved")
        return append(root, {"feature": target.get("feature"), "phase": "user", "decision": args.answer, "why": "the user's call",
                             "evidence": args.id, "result": "resolved", "resolves": args.id})
    if args.feature:
        load(root, args.feature)
    row = {"feature": args.feature, "phase": args.phase, "decision": args.decision, "why": args.why, "evidence": args.evidence,
           "result": args.result}
    if args.waiting:
        if not (args.pick and args.risk):
            raise TrackerError("a call waiting on the user names your --pick and its --risk, so the user can decide from the row alone")
        row.update(waiting=True, pick=args.pick, risk=args.risk, result=args.result or "waiting on the user")
    return append(root, row)
