"""Read-only HTTP server for the dashboard: JSON API, server-sent events, and the static single-page app.

Data comes from the tracker and spec CLIs (`--json`, run with the project root as cwd) and from reading
`implementation/` and `specs/` directly. Nothing here ever writes to the project.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from statistics import median
from typing import Any
from urllib.parse import unquote, urlsplit

STATIC = Path(__file__).resolve().parent / "static"
STATIC_FILES = {"/": "index.html", "/index.html": "index.html", "/app.js": "app.js", "/app.css": "app.css"}
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8"}
SCRIPTS = Path(__file__).resolve().parents[1]
TRACKER_CLI = SCRIPTS / "spec_tracker.py"
SPEC_CLI = Path(__file__).resolve().parents[3] / "spec-cli" / "scripts" / "spec.py"

SPEC_ID = re.compile(r"^[0-9]{1,6}(?:-[a-z0-9]+(?:-[a-z0-9]+)*)?$")
FEATURE_ID = re.compile(r"^[0-9]{4}-[a-z0-9]+(?:-[a-z0-9]+)*$")
TERMINAL_BUGS = {"verified", "closed_not_a_bug", "follow_up"}
STAGES = ("draft", "ready", "planning", "implementing", "review", "test", "merge", "accepted", "deferred")
SCAN_INTERVAL = 1.0
CLI_TIMEOUT = 30


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def seconds_between(start: Any, end: Any) -> float | None:
    first, last = parse_time(start), parse_time(end)
    return (last - first).total_seconds() if first and last else None


def short(text: Any, limit: int = 400) -> str:
    value = str(text or "")
    return value if len(value) <= limit else value[: limit - 1] + "…"


def ids_of(items: Any) -> list[int]:
    """Spec ids found in a CLI list whose entries may be ints, objects with an id, or nested lists."""
    found: list[int] = []
    for item in items or []:
        if isinstance(item, bool):
            continue
        if isinstance(item, int):
            found.append(item)
        elif isinstance(item, dict) and isinstance(item.get("id"), int):
            found.append(item["id"])
        elif isinstance(item, list):
            found.extend(ids_of(item))
    return found


class Project:
    """A project root plus a cache invalidated whenever a file under implementation/ or specs/ changes."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.name = root.name
        self.lock = threading.RLock()
        self.cache: dict[str, Any] = {}
        self.cache_signature = ""
        self.scan_at = 0.0
        self.scan_value = ""

    def signature(self) -> str:
        with self.lock:
            now = time.monotonic()
            if now - self.scan_at < SCAN_INTERVAL / 2 and self.scan_value:
                return self.scan_value
            digest = hashlib.sha1()
            for top in ("implementation", "specs"):
                for folder, directories, files in os.walk(self.root / top):
                    directories.sort()
                    for name in sorted(files):
                        path = os.path.join(folder, name)
                        try:
                            stat = os.stat(path)
                        except OSError:
                            continue
                        digest.update(f"{path}:{stat.st_mtime_ns}:{stat.st_size}\n".encode())
            self.scan_value, self.scan_at = digest.hexdigest(), now
            return self.scan_value

    def cached(self, key: str, build: Any) -> Any:
        with self.lock:
            signature = self.signature()
            if signature != self.cache_signature:
                self.cache, self.cache_signature = {}, signature
            if key not in self.cache:
                self.cache[key] = build()
            return self.cache[key]

    def run(self, script: Path, *arguments: str) -> Any | None:
        """Result of a CLI call with --json, or None when the command is missing or fails."""
        try:
            process = subprocess.run(
                [sys.executable, str(script), "--json", *arguments],
                cwd=self.root, text=True, capture_output=True, check=False, timeout=CLI_TIMEOUT,
            )
            payload = json.loads(process.stdout)
        except (OSError, subprocess.SubprocessError, ValueError):
            return None
        if not isinstance(payload, dict) or payload.get("ok") is False:
            return None
        return payload.get("result", payload)

    def read_json(self, path: Path) -> Any | None:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    # Loaders ---------------------------------------------------------------------------------------------

    def records(self) -> dict[str, dict[str, Any]]:
        def load() -> dict[str, dict[str, Any]]:
            found: dict[str, dict[str, Any]] = {}
            for location in ("archive", "active"):
                folder = self.root / "implementation" / location
                for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
                    record = self.read_json(path)
                    if isinstance(record, dict) and FEATURE_ID.match(str(record.get("feature", ""))):
                        found[record["feature"]] = {"record": record, "location": location}
            return found
        return self.cached("records", load)

    def spec_archive(self) -> dict[str, Any]:
        data = self.cached("spec_archive", lambda: self.read_json(self.root / "implementation" / "spec-archive.json"))
        return data if isinstance(data, dict) else {"archived": {}, "history": []}

    def specs(self) -> list[dict[str, Any]]:
        result = self.cached("spec_list", lambda: self.run(SPEC_CLI, "list"))
        return result if isinstance(result, list) else []

    def waves(self) -> dict[str, Any]:
        result = self.cached("waves", lambda: self.run(SPEC_CLI, "waves"))
        return result if isinstance(result, dict) else {}

    def pr_status(self) -> dict[str, Any] | None:
        result = self.cached("pr_status", lambda: self.run(TRACKER_CLI, "pr", "status"))
        return result if isinstance(result, dict) and isinstance(result.get("prs"), list) else None

    def queue_status(self) -> dict[str, Any] | None:
        result = self.cached("queue_status", lambda: self.run(TRACKER_CLI, "queue", "status"))
        return result if isinstance(result, dict) and isinstance(result.get("queues"), dict) else None

    def main_heads(self) -> dict[str, str]:
        workspace = self.read_json(self.root / "implementation" / "workspace.json")
        heads: dict[str, str] = {}
        if not isinstance(workspace, dict):
            return heads
        for repo in workspace.get("repos", []):
            checkout = self.root / str(repo) / str(workspace.get("main", "main"))
            try:
                process = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=checkout, text=True, capture_output=True,
                                         check=False, timeout=5)
            except (OSError, subprocess.SubprocessError):
                continue
            if process.returncode == 0 and process.stdout.strip():
                heads[str(repo)] = process.stdout.strip()
        return heads


# Derivations from records -------------------------------------------------------------------------------------


def open_bugs(record: dict[str, Any]) -> list[dict[str, Any]]:
    return [bug for bug in record.get("bugs", []) if bug.get("status") not in TERMINAL_BUGS]


def record_stage(status: str, role: str) -> str:
    if status == "accepted":
        return "accepted"
    if status in {"new", "planning"}:
        return "planning"
    if status == "ready_for_review":
        return "review"
    if status in {"ready_for_test", "ready_for_retest"}:
        return "test"
    if status == "ready_for_acceptance":
        return "merge"
    return "test" if role == "tester" else "review" if role == "reviewer" else "implementing"


def active_assignments(record: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in record.get("assignments", []) if item.get("status") == "active"]


def archive_time(project: Project, feature: str) -> str | None:
    entry = project.spec_archive().get("archived", {}).get(f"{feature}.md")
    return entry.get("archived_at") if isinstance(entry, dict) else None


def merged_time(project: Project, entry: dict[str, Any]) -> str | None:
    record = entry["record"]
    if entry["location"] != "archive" and record.get("status") != "accepted":
        return None
    return (record.get("worktree") or {}).get("merged_at") or archive_time(project, record["feature"]) or record.get("updated_at")


def review_rounds(record: dict[str, Any]) -> int:
    claimed = [item for item in record.get("assignments", []) if item.get("role") == "reviewer"]
    return len(claimed) or int(any(item.get("role") == "reviewer" for item in record.get("checks", [])))


def pill(record: dict[str, Any], stage: str) -> dict[str, str]:
    status, role = str(record.get("status", "")), str(record.get("current_role", ""))
    if stage == "accepted":
        return {"key": "merged", "label": "Merged"}
    if status == "bugs_found" or (open_bugs(record) and stage != "merge"):
        return {"key": "bugs", "label": "Bugs found"}
    if status in {"blocked", "needs_answer", "needs_tooling"}:
        return {"key": "blocked", "label": {"blocked": "Blocked", "needs_answer": "Needs an answer", "needs_tooling": "Needs tooling"}[status]}
    if stage == "planning":
        return {"key": "plan", "label": "Planning"}
    if stage == "review":
        return {"key": "review", "label": "In review"}
    if stage == "test":
        return {"key": "test", "label": "Testing"} if role == "tester" else {"key": "waitTest", "label": "Waiting for test"}
    if stage == "merge":
        return {"key": "merge", "label": "Ready to merge"}
    batches = len(((record.get("plans") or [{}])[-1]).get("batches", []))
    current = [item.get("batch") for item in active_assignments(record) if item.get("batch")]
    suffix = f" · batch {current[0]}/{batches}" if current and batches else ""
    return {"key": "impl", "label": "Implementing" + suffix}


def derive_pr(project: Project, entry: dict[str, Any], spec: dict[str, Any] | None) -> dict[str, Any]:
    record = entry["record"]
    feature = record["feature"]
    merged_at = merged_time(project, entry)
    stage = record_stage(str(record.get("status", "")), str(record.get("current_role", "")))
    worktree = record.get("worktree") or {}
    repos: dict[str, Any] = {}
    for repo in worktree.get("repos", []) if not worktree.get("removed_at") else []:
        repos[repo] = {"branch": worktree.get("branch"), "path": f"{repo}/{worktree.get('branch')}"}
    checks = latest_checks(record)
    requirements = record.get("requirements", [])
    bugs = record.get("bugs", [])
    by_finder: dict[str, int] = {}
    for bug in bugs:
        by_finder[str(bug.get("found_by", "?"))] = by_finder.get(str(bug.get("found_by", "?")), 0) + 1
    return {
        "feature": feature, "spec_id": feature[:4], "title": (spec or {}).get("title") or record.get("title") or feature,
        "state": "merged" if merged_at else "open", "opened_at": record.get("created_at"), "merged_at": merged_at,
        "updated_at": record.get("updated_at"),
        "record_status": record.get("status"), "current_role": record.get("current_role"), "model": None,
        "stage": stage, "pill": pill(record, stage), "risk": record.get("risk", "normal"),
        "repos": repos, "fast_ci": None, "queue": None, "review_rounds": review_rounds(record),
        "checks": {"passed": sum(1 for item in checks if item.get("result") == "passed"),
                   "failed": sum(1 for item in checks if item.get("result") == "failed"), "total": len(checks)},
        "requirements": {"total": len(requirements), "implemented": sum(1 for item in requirements if item.get("implemented")),
                         "tested": sum(1 for item in requirements if item.get("tested"))},
        "bugs": {"total": len(bugs), "open": len(open_bugs(record)), "by_finder": by_finder},
        "running": [{"role": item.get("role"), "assignment": item.get("id"), "batch": item.get("batch"), "since": item.get("at")}
                    for item in active_assignments(record)],
    }


def latest_checks(record: dict[str, Any]) -> list[dict[str, Any]]:
    generation = int(record.get("generation", 1))
    current = [item for item in record.get("checks", []) if int(item.get("generation", 1)) == generation]
    return list({item.get("name"): item for item in current}.values())


def build_prs(project: Project) -> dict[str, Any]:
    def build() -> dict[str, Any]:
        specs = {item["feature"]: item for item in project.specs()}
        rows = {feature: derive_pr(project, entry, specs.get(feature)) for feature, entry in project.records().items()}
        status = project.pr_status()
        for item in (status or {}).get("prs", []):
            if not isinstance(item, dict) or not FEATURE_ID.match(str(item.get("feature", ""))):
                continue
            row = rows.setdefault(item["feature"], {"feature": item["feature"], "spec_id": item["feature"][:4], "title": item["feature"],
                                                    "pill": {"key": "impl", "label": "Open"}, "stage": "implementing", "bugs": {"open": 0}})
            row.update({key: value for key, value in item.items() if value is not None and key not in {"title", "review_rounds"}})
            if item.get("title"):
                row["title"] = item["title"]
            if isinstance(item.get("review_rounds"), int):
                row["review_rounds"] = item["review_rounds"]
            if item.get("state") == "merged" and row.get("stage") != "accepted":
                row["stage"], row["pill"] = "accepted", {"key": "merged", "label": "Merged"}
        ordered = sorted(rows.values(), key=lambda item: str(item.get("merged_at") or item.get("updated_at") or ""), reverse=True)
        return {"prs": ordered, "source": "pr status" if status else "records", "pr_status_available": status is not None}
    return project.cached("prs", build)


def build_queues(project: Project) -> dict[str, Any]:
    def build() -> dict[str, Any]:
        status = project.queue_status()
        prs = build_prs(project)["prs"]
        counters = build_counters(project, prs)
        if status:
            return {"available": True, "source": "queue status", "queues": status["queues"], "agents": status.get("agents", []),
                    "counters": counters}
        queues: dict[str, Any] = {"review": {"slots": {}, "holders": [], "waiting": []}, "test": {"slots": {}, "holders": [], "waiting": []},
                                  "merge": {"slots": {}, "holders": [], "waiting": []}}
        agents = []
        for row in prs:
            if row["state"] != "open":
                continue
            entry = project.records()[row["feature"]]
            for item in active_assignments(entry["record"]):
                agents.append({"assignment": item.get("id"), "feature": row["feature"], "role": item.get("role"), "model": None,
                               "batch": item.get("batch"), "claimed_at": item.get("at")})
            slot = {"review": "review", "test": "test", "merge": "merge"}.get(row["stage"])
            if slot:
                queues[slot]["waiting" if row["pill"]["key"] in {"waitTest", "merge"} else "holders"].append(
                    {"feature": row["feature"], "class": "default", "since": row.get("updated_at"), "position": None})
        return {"available": False, "source": "records", "queues": queues, "agents": agents, "counters": counters}
    return project.cached("queues", build)


def build_counters(project: Project, prs: list[dict[str, Any]]) -> dict[str, Any]:
    merged = [row for row in prs if row["state"] == "merged" and row.get("merged_at")]
    merged.sort(key=lambda row: row["merged_at"], reverse=True)
    today = datetime.now().astimezone().date()
    merged_today = [row for row in merged if (parse_time(row["merged_at"]) or datetime.min.replace(tzinfo=timezone.utc))
                    .astimezone().date() == today]
    spans = [seconds_between(row["opened_at"], row["merged_at"]) for row in merged[:20]]
    spans = [value for value in spans if value is not None and value >= 0]
    rounds = [row.get("review_rounds") or 0 for row in merged[:10]]
    finders: dict[str, int] = {}
    waits: list[float] = []
    for entry in project.records().values():
        record = entry["record"]
        for bug in record.get("bugs", []):
            finders[str(bug.get("found_by", "?"))] = finders.get(str(bug.get("found_by", "?")), 0) + 1
        reviews = [item["at"] for item in record.get("checks", []) if item.get("role") == "reviewer" and item.get("result") == "passed"]
        tests = [item["at"] for item in record.get("assignments", []) if item.get("role") == "tester"]
        if reviews and tests:
            wait = seconds_between(max(reviews), min(tests))
            if wait is not None and wait >= 0:
                waits.append(wait)
    return {
        "merged_today": len(merged_today), "median_seconds_to_merge": median(spans) if spans else None,
        "review_rounds_per_spec": round(sum(rounds) / len(rounds), 1) if rounds else None, "review_rounds_sample": len(rounds),
        "bugs_by_finder": finders, "median_test_wait_seconds": median(waits) if waits else None,
    }


# Specs --------------------------------------------------------------------------------------------------------


def spec_stage(spec: dict[str, Any], entry: dict[str, Any] | None, ready: set[int]) -> str:
    if spec["status"] == "deferred":
        return "deferred"
    if entry and entry["location"] == "active":
        return record_stage(str(entry["record"].get("status", "")), str(entry["record"].get("current_role", "")))
    if spec["status"] in {"accepted", "superseded"}:
        return "accepted"
    if spec["status"] == "in_progress":
        return "planning"
    return "ready" if spec["id"] in ready else "draft"


def wave_numbers(project: Project) -> tuple[dict[int, int], set[int]]:
    waves = project.waves()
    numbers: dict[int, int] = {}
    for index, level in enumerate(waves.get("waves", []) or [], start=1):
        for spec_id in ids_of(level if isinstance(level, list) else [level]) or ids_of(level.get("specs", []) if isinstance(level, dict) else []):
            numbers[spec_id] = index
    return numbers, set(ids_of(waves.get("startable"))) | set(ids_of(waves.get("plannable")))


def updated_for(project: Project, spec: dict[str, Any], entry: dict[str, Any] | None) -> str:
    if entry and entry["location"] == "active":
        return str(entry["record"].get("updated_at") or "")
    return archive_time(project, spec["feature"]) or (entry["record"].get("updated_at") if entry else None) or str(spec.get("created") or "")


def build_specs(project: Project) -> dict[str, Any]:
    def build() -> dict[str, Any]:
        records = project.records()
        numbers, ready = wave_numbers(project)
        rows = []
        counts = {stage: 0 for stage in STAGES}
        for spec in project.specs():
            entry = records.get(spec["feature"])
            stage = spec_stage(spec, entry, ready)
            counts[stage] += 1
            rows.append({
                "id": spec["id"], "feature": spec["feature"], "title": spec["title"], "kind": spec["kind"], "status": spec["status"],
                "stage": stage, "depends_on": spec.get("depends_on", []), "wave": numbers.get(spec["id"]),
                "updated": updated_for(project, spec, entry), "has_record": entry is not None,
            })
        rows.sort(key=lambda row: row["id"], reverse=True)
        return {"specs": rows, "stages": counts, "kinds": sorted({row["kind"] for row in rows})}
    return project.cached("specs_view", build)


REQUIREMENT_LINE = re.compile(r"\*\*(R\d+)\*\*")
AMENDS = re.compile(r"\(amends ([^)]*)\)")


def strip_frontmatter(text: str) -> str:
    if text.startswith("---\n"):
        end = text.find("\n---", 4)
        if end != -1:
            return text[end + 4:].lstrip("\n")
    return text


def requirement_marks(spec: dict[str, Any], record: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    marks: dict[str, dict[str, Any]] = {}
    for item in (record or {}).get("requirements", []):
        reference = str(item.get("spec_ref", ""))
        number, _, requirement = reference.partition(":")
        if requirement and number.isdigit() and int(number) == spec["id"]:
            amends = AMENDS.search(str(item.get("verification", "")))
            marks[requirement] = {"id": item.get("id"), "implemented": bool(item.get("implemented")), "tested": bool(item.get("tested")),
                                  "amends": amends.group(1) if amends else ""}
    return marks


def lifecycle(project: Project, spec: dict[str, Any], record: dict[str, Any] | None) -> list[dict[str, Any]]:
    record = record or {}
    checks = record.get("checks", [])
    reviewed = [item["at"] for item in checks if item.get("role") == "reviewer" and item.get("result") == "passed"]
    tested = [item["at"] for item in checks if item.get("role") == "tester" and item.get("result") == "passed"]
    implemented = [item["implemented_at"] for item in record.get("requirements", []) if item.get("implemented_at")]
    history = [item for item in project.spec_archive().get("history", []) if item.get("specification") == f"{spec['feature']}.md"]
    restores = [item["at"] for item in history if item.get("action") == "restore"]
    archives = [item["at"] for item in history if item.get("action") in {"archive", "baseline"}]
    plans = [item["at"] for item in record.get("plans", []) if item.get("at")]
    steps: list[tuple[str, Any]] = [
        ("Draft", spec.get("created")), ("Planned", plans[0] if plans else None), ("Implemented", max(implemented) if implemented else None),
        ("Reviewed", min(reviewed) if reviewed else None), ("Tested", max(tested) if tested else None),
        ("Merged", (record.get("worktree") or {}).get("merged_at")),
    ]
    if restores:
        steps.append(("Restored", restores[-1]))
    steps.append(("Accepted", archives[-1] if archives and spec["status"] in {"accepted", "superseded"} else None))
    return [{"name": name, "at": at, "done": bool(at)} for name, at in steps]


def spec_history(project: Project, spec: dict[str, Any], record: dict[str, Any] | None) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = [{"action": "created", "at": spec.get("created"), "detail": f"specs/{spec['feature']}.md"}]
    for item in project.spec_archive().get("history", []):
        if item.get("specification") != f"{spec['feature']}.md":
            continue
        detail = item.get("reason") or ""
        if item.get("action") == "edit":
            detail = f"{detail} (via {item.get('via')})" if item.get("via") else detail
        events.append({"action": item.get("action"), "at": item.get("at"), "detail": short(detail), "user_decision": item.get("user_decision")})
    for plan in (record or {}).get("plans", []):
        events.append({"action": "plan", "at": plan.get("at"), "detail": f"plan v{plan.get('version', '?')}: {len(plan.get('batches', []))} batches"})
    merged = ((record or {}).get("worktree") or {}).get("merged_at")
    if merged:
        events.append({"action": "merged", "at": merged, "detail": "worktree merged into main"})
    return sorted(events, key=lambda item: str(item.get("at") or ""))


def spec_decisions(project: Project, spec: dict[str, Any], record: dict[str, Any] | None) -> list[dict[str, Any]]:
    decisions = [{"source": f"spec {item['action']}", "at": item.get("at"), "text": item["user_decision"], "reason": short(item.get("reason"))}
                 for item in project.spec_archive().get("history", [])
                 if item.get("specification") == f"{spec['feature']}.md" and item.get("user_decision")]
    for item in (record or {}).get("dependency_overrides", []) or []:
        if item.get("user_decision"):
            decisions.append({"source": "dependency override", "at": item.get("at"), "text": item["user_decision"], "reason": ""})
    for item in (record or {}).get("specification", {}).get("history", []) or []:
        if item.get("user_decision"):
            decisions.append({"source": "spec sync", "at": item.get("at"), "text": item["user_decision"], "reason": short(item.get("reason"))})
    for item in (record or {}).get("questions", []) or []:
        if item.get("status") == "answered":
            decisions.append({"source": f"question from {item.get('role', '?')}", "at": item.get("answered_at"), "text": short(item.get("answer")),
                              "reason": short(item.get("text"))})
    waiver = (record or {}).get("plan_waiver")
    if isinstance(waiver, dict) and waiver.get("user_decision"):
        decisions.append({"source": "plan waiver", "at": waiver.get("at"), "text": waiver["user_decision"], "reason": short(waiver.get("reason"))})
    return sorted(decisions, key=lambda item: str(item.get("at") or ""))


def find_spec(project: Project, identifier: str) -> dict[str, Any] | None:
    if not SPEC_ID.match(identifier):
        return None
    number = int(identifier.split("-")[0])
    return next((item for item in project.specs() if item["id"] == number), None)


def build_spec(project: Project, identifier: str) -> dict[str, Any] | None:
    spec = find_spec(project, identifier)
    if spec is None:
        return None

    def build() -> dict[str, Any]:
        entry = project.records().get(spec["feature"])
        record = entry["record"] if entry else None
        specs_dir = (project.root / "specs").resolve()
        path = (project.root / spec["path"]).resolve()
        try:
            body = strip_frontmatter(path.read_text(encoding="utf-8")) if path.is_relative_to(specs_dir) else ""
        except OSError:
            body = ""
        effective = project.run(SPEC_CLI, "show", str(spec["id"]), "--effective")
        titles = {item["id"]: item for item in project.specs()}
        relation = lambda key: [{"id": number, "title": titles[number]["title"], "status": titles[number]["status"]}  # noqa: E731
                                for number in spec.get(key, []) if number in titles]
        pr = None
        if entry:
            pr = build_prs(project)
            pr = next((row for row in pr["prs"] if row["feature"] == spec["feature"]), None)
        return {
            "spec": spec, "stage": spec_stage(spec, entry, wave_numbers(project)[1]), "body": body,
            "effective": effective if isinstance(effective, list) else [], "requirements": requirement_marks(spec, record),
            "lifecycle": lifecycle(project, spec, record), "history": spec_history(project, spec, record),
            "decisions": spec_decisions(project, spec, record),
            "links": {key: relation(key) for key in ("depends_on", "amends", "references", "amended_by", "supersedes", "superseded_by")},
            "pr": pr,
        }
    return project.cached(f"spec:{spec['id']}", build)


# Records -------------------------------------------------------------------------------------------------------

ROLE_NAMES = {"parent": "Parent", "planner": "Planner", "implementer": "Implementer", "reviewer": "Reviewer", "tester": "Tester",
              "fixer": "Fixer", "toolsmith": "Toolsmith"}


def timeline(record: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []

    def add(at: Any, kind: str, who: str, what: str, note: str = "") -> None:
        if at:
            events.append({"at": at, "kind": kind, "who": who, "what": what, "note": short(note)})

    worktree = record.get("worktree") or {}
    add(record.get("created_at"), "created", "Parent", "created the record" + (" and the worktrees" if worktree else ""))
    for plan in record.get("plans", []):
        add(plan.get("at"), "plan", ROLE_NAMES.get(plan.get("added_by", "planner"), "Planner"),
            f"stored plan v{plan.get('version', '?')}: {len(plan.get('batches', []))} batches")
    for item in record.get("assignments", []):
        role = str(item.get("role"))
        if item.get("auto") and role == "planner":
            continue
        batch = f" batch {item['batch']}" if item.get("batch") else ""
        add(item.get("at"), "work", ROLE_NAMES.get(role, role.title()), f"started{batch}", f"{item.get('id')} · {len(item.get('paths', []))} paths")
    for item in record.get("checks", []):
        result = str(item.get("result"))
        kind = "check_pass" if result == "passed" else "check_fail" if result == "failed" else "check_other"
        role = str(item.get("role", "parent"))
        add(item.get("at"), kind, ROLE_NAMES.get(role, role.title()), f"recorded {item.get('name')}: {result.replace('_', ' ')}",
            item.get("evidence", ""))
    for item in record.get("questions", []) or []:
        role = str(item.get("role", "?"))
        add(item.get("at"), "question", ROLE_NAMES.get(role, role.title()), "asked a question", item.get("text", ""))
        add(item.get("answered_at"), "answer", "Parent", "answered", item.get("answer", ""))
    for item in record.get("generation_history", []) or []:
        add(item.get("at"), "generation", "Workflow", f"started revision {item.get('to')}", item.get("reason", ""))
    add(worktree.get("merged_at"), "merge", "Parent", "merged the branches into main")
    return sorted(events, key=lambda item: item["at"])


def changed_files(record: dict[str, Any]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    branch = (record.get("worktree") or {}).get("branch")
    for path in record.get("changed_files", []) or []:
        parts = str(path).split("/")
        repo = parts[0] if len(parts) > 1 else "."
        rest = parts[2:] if len(parts) > 2 and branch and parts[1] in {branch, "main"} else parts[1:]
        grouped.setdefault(repo, []).append("/".join(rest))
    return grouped


def build_record(project: Project, feature: str) -> dict[str, Any] | None:
    if not FEATURE_ID.match(feature):
        return None
    entry = project.records().get(feature)
    if entry is None:
        return None

    def build() -> dict[str, Any]:
        record = entry["record"]
        pr = next((row for row in build_prs(project)["prs"] if row["feature"] == feature), derive_pr(project, entry, None))
        specs = {item["id"]: item for item in project.specs()}
        spec = next((item for item in specs.values() if item["feature"] == feature), None)
        checks = [{"name": item.get("name"), "role": item.get("role"), "result": item.get("result"), "method": item.get("method"),
                   "evidence": short(item.get("evidence"), 600), "at": item.get("at")} for item in latest_checks(record)]
        for command in (pr.get("fast_ci") or {}).get("commands", []) or []:
            checks.append({"name": f"fast-ci/{command.get('repo')}", "role": "merge queue", "result": "passed" if command.get("exit") == 0 else "failed",
                           "method": command.get("command"), "evidence": f"exit {command.get('exit')}", "seconds": command.get("seconds"),
                           "log": (pr.get("fast_ci") or {}).get("log"), "at": (pr.get("fast_ci") or {}).get("at")})
        plan = (record.get("plans") or [None])[-1]
        requirements = [{"id": item.get("id"), "spec_ref": item.get("spec_ref"), "text": short(item.get("verification"), 600),
                         "implemented": bool(item.get("implemented")), "tested": bool(item.get("tested")),
                         "implementation": item.get("implementation"), "implementation_evidence": short(item.get("implementation_evidence"), 600),
                         "test_evidence": short(item.get("test_evidence"), 600)} for item in record.get("requirements", [])]
        bugs = [{"id": item.get("id"), "title": item.get("title"), "severity": item.get("severity"), "status": item.get("status"),
                 "found_by": item.get("found_by"), "spec_ref": item.get("spec_ref"), "reproduction": short(item.get("reproduction"), 800),
                 "fix": short(item.get("fix"), 600), "retest": short(item.get("retest"), 600)} for item in record.get("bugs", [])]
        by_status: dict[str, int] = {}
        for item in bugs:
            by_status[str(item["status"])] = by_status.get(str(item["status"]), 0) + 1
        roles = [item.get("role") for item in record.get("assignments", [])]
        start, end = record.get("created_at"), pr.get("merged_at") or datetime.now(timezone.utc).isoformat()
        return {
            "pr": pr, "feature": feature, "location": entry["location"], "timeline": timeline(record), "checks": checks,
            "requirements": requirements, "bugs": bugs, "files": changed_files(record),
            "plan": None if not plan else {"version": plan.get("version"), "ownership": plan.get("ownership"), "text": short(plan.get("text"), 20000),
                                           "batches": [{"number": item.get("number"), "title": item.get("title"), "requirements": item.get("requirements"),
                                                        "requires": item.get("requires"), "text": short(item.get("text"), 6000)}
                                                       for item in plan.get("batches", [])]},
            "sidebar": {
                "running": pr["running"], "bugs_by_status": by_status, "bugs_by_finder": pr["bugs"].get("by_finder", {}),
                "batches": len((plan or {}).get("batches", [])), "reviews": roles.count("reviewer"), "fixes": roles.count("fixer"),
                "open_seconds": seconds_between(start, end),
                "depends_on": [{"id": number, "title": specs[number]["title"], "status": specs[number]["status"]}
                               for number in (spec or {}).get("depends_on", []) if number in specs],
            },
        }
    return project.cached(f"record:{feature}", build)


def build_activity(project: Project) -> dict[str, Any]:
    def build() -> dict[str, Any]:
        events: list[dict[str, Any]] = []
        for feature, entry in project.records().items():
            for item in timeline(entry["record"]):
                if item["kind"] in {"created", "plan", "merge", "question", "answer"}:
                    events.append({**item, "feature": feature})
        for item in project.spec_archive().get("history", []):
            name = str(item.get("specification", ""))
            if item.get("action") in {"archive", "restore", "defer", "undefer", "unlock", "relock", "edit"}:
                events.append({"at": item.get("at"), "kind": "spec", "who": "Spec", "what": f"{item.get('action')}", "feature": name.removesuffix(".md"),
                               "note": short(item.get("reason"))})
        events = [item for item in events if item.get("at")]
        events.sort(key=lambda item: str(item["at"]), reverse=True)
        return {"events": events[:300]}
    return project.cached("activity", build)


# HTTP ----------------------------------------------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    server_version = "tracker-ui"
    project: Project

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass

    def send_body(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, payload: Any, status: int = 200) -> None:
        self.send_body(status, "application/json; charset=utf-8", json.dumps(payload, ensure_ascii=False).encode("utf-8"))

    def send_error_json(self, status: int, message: str) -> None:
        self.send_json({"error": message}, status)

    def do_GET(self) -> None:  # noqa: N802
        path = unquote(urlsplit(self.path).path)
        try:
            if path in STATIC_FILES:
                self.serve_static(STATIC_FILES[path])
            elif path == "/api/events":
                self.serve_events()
            elif path.startswith("/api/"):
                self.serve_api(path)
            else:
                self.send_error_json(HTTPStatus.NOT_FOUND, "not found")
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self) -> None:  # noqa: N802
        self.send_error_json(HTTPStatus.METHOD_NOT_ALLOWED, "read-only dashboard")

    do_PUT = do_PATCH = do_DELETE = do_POST

    def serve_static(self, name: str) -> None:
        file = STATIC / name
        try:
            body = file.read_bytes()
        except OSError:
            self.send_error_json(HTTPStatus.NOT_FOUND, "missing static file")
            return
        self.send_body(200, CONTENT_TYPES[file.suffix], body)

    def serve_api(self, path: str) -> None:
        project = self.project
        parts = path.strip("/").split("/")
        name = parts[1] if len(parts) > 1 else ""
        if len(parts) == 2:
            static = {"prs": build_prs, "queues": build_queues, "specs": build_specs, "activity": build_activity}
            if name in static:
                self.send_json(static[name](project))
            elif name == "meta":
                self.send_json(self.meta())
            else:
                self.send_error_json(HTTPStatus.NOT_FOUND, "unknown endpoint")
        elif len(parts) >= 3 and name in {"spec", "record"}:
            identifier = "/".join(parts[2:])
            valid = SPEC_ID.match(identifier) if name == "spec" else FEATURE_ID.match(identifier)
            if not valid:
                self.send_error_json(HTTPStatus.BAD_REQUEST, "invalid id")
                return
            result = build_spec(project, identifier) if name == "spec" else build_record(project, identifier)
            if result is None:
                self.send_error_json(HTTPStatus.NOT_FOUND, f"unknown {name}")
            else:
                self.send_json(result)
        else:
            self.send_error_json(HTTPStatus.NOT_FOUND, "unknown endpoint")

    def meta(self) -> dict[str, Any]:
        project = self.project
        queues = build_queues(project)
        return {"project": project.name, "root": str(project.root), "main": project.main_heads(), "queues_available": queues["available"],
                "pr_status_available": build_prs(project)["pr_status_available"], "signature": project.signature()}

    def serve_events(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        project = self.project
        last = project.signature()
        self.wfile.write(f"retry: 2000\nevent: hello\ndata: {json.dumps({'signature': last})}\n\n".encode())
        self.wfile.flush()
        idle = 0.0
        while not getattr(self.server, "stopping", False):
            time.sleep(SCAN_INTERVAL)
            current = project.signature()
            if current != last:
                last, idle = current, 0.0
                self.wfile.write(f"event: change\ndata: {json.dumps({'signature': current})}\n\n".encode())
            else:
                idle += SCAN_INTERVAL
                if idle >= 15:
                    idle = 0.0
                    self.wfile.write(b": keep-alive\n\n")
            self.wfile.flush()


class DashboardServer(ThreadingHTTPServer):
    daemon_threads = True
    stopping = False


def make_server(root: Path, port: int, host: str) -> DashboardServer:
    handler = type("BoundHandler", (Handler,), {"project": Project(root)})
    return DashboardServer((host, port), handler)


def main(root: Path, port: int, host: str = "127.0.0.1") -> None:
    server = make_server(root, port, host)
    print(f"spec-workflow dashboard for {root.name}: http://{host}:{server.server_address[1]}/ (read-only, Ctrl-C to stop)", flush=True)
    try:
        server.serve_forever()
    finally:
        server.stopping = True
        server.server_close()
