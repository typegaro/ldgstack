"""Conformance: did the run follow the workflow rules that prose alone used to carry? Deterministic, read-only."""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from .transcripts import Run

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "spec-tracker" / "scripts"))

from tracker import paths as lanes  # noqa: E402
from tracker.deps import prerequisites  # noqa: E402

SPEC_FILE = re.compile(r"(?:^|/)specs/([0-9]{4}-[a-z0-9-]+\.md)$")
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
VERIFIER_ROLES = ("reviewer", "tester")
EVIDENCE_LIMIT = 6


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def records(root: Path) -> list[dict[str, Any]]:
    found = []
    for directory in ("archive", "active"):
        for path in sorted((root / "implementation" / directory).glob("*.json")):
            value = read_json(path)
            if isinstance(value, dict) and "feature" in value:
                found.append(value)
    return found


def check(key: str, title: str, evidence: list[str], rule: str) -> dict[str, Any]:
    return {"key": key, "title": title, "violations": len(evidence), "evidence": sorted(evidence)[:EVIDENCE_LIMIT], "enforced_by": rule}


def label(run: Run) -> str:
    return f"{run.role} {run.id[:8]} ({run.description[:40]})"


def early_starts(root: Path, items: list[dict[str, Any]], manifest: dict[str, Any]) -> list[str]:
    # First acceptance time per spec; archived entries without history (adopted baselines) count as accepted from the start.
    accepted_at: dict[str, str] = {name: str(entry.get("archived_at") or "") for name, entry in (manifest.get("archived") or {}).items()
                                   if isinstance(entry, dict)}
    for entry in manifest.get("history") or []:
        if isinstance(entry, dict) and entry.get("action") == "archive":
            name, at = str(entry.get("specification")), str(entry.get("at", ""))
            accepted_at[name] = min(at, accepted_at.get(name, at))
    found = []
    for record in items:
        spec = root / str((record.get("specification") or {}).get("path", ""))
        if not spec.is_file():
            continue
        overridden = any(item.get("user_decision") for item in record.get("dependency_overrides") or [])
        for target in prerequisites(spec):
            names = sorted(path.name for path in (root / "specs").glob(f"{target:04d}-*.md"))
            name = names[0] if names else f"{target:04d}"
            at = accepted_at.get(name)
            if (at is None or at > str(record.get("created_at", ""))) and not overridden:
                found.append(f"{record['feature']} started {record.get('created_at', '?')[:16]} before {name} was accepted ({(at or 'never')[:16]})")
    return found


def relative(root: Path, path: str) -> str | None:
    try:
        return Path(path).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return None


def outside_lanes(root: Path, runs: list[Run], items: list[dict[str, Any]]) -> list[str]:
    assignments = {item["id"]: item for record in items for item in record.get("assignments") or [] if isinstance(item, dict) and "id" in item}
    found = []
    for run in runs:
        if run.kind != "subagent":
            continue
        try:
            bound = lanes.marker(root, run.id).read_text(encoding="utf-8").strip()
        except OSError:
            bound = ""
        own = assignments.get(bound)
        for call in run.calls:
            if call.name not in EDIT_TOOLS or not call.path:
                continue
            path = relative(root, call.path)
            if path is None or path.startswith("specs/.drafts/"):
                continue
            if run.role in VERIFIER_ROLES:
                found.append(f"{label(run)} edited {path} (read-only role)")
            elif own is not None and not lanes.matches(own.get("paths") or [], path):
                found.append(f"{label(run)} edited {path} outside {own['id']}")
    return found


def non_fresh(runs: list[Run]) -> list[str]:
    roles = {run.id: run.role for run in runs}
    found = []
    for run in runs:
        if run.kind == "subagent" and run.role in VERIFIER_ROLES:
            features = sorted({feature for call in run.calls for feature in call.features})
            if len(features) > 1:
                found.append(f"{label(run)} worked on {len(features)} specs: {', '.join(features[:4])}")
        if run.kind == "main":
            for call in run.calls:
                if call.name == "SendMessage" and call.role_hint in VERIFIER_ROLES:
                    target = next((role for agent, role in roles.items() if call.target and agent.startswith(call.target)), "")
                    if target and target != call.role_hint:
                        found.append(f"parent sent a {call.role_hint} task to a {target} agent ({call.target[:8]})")
    return found


def missing_decisions(root: Path, runs: list[Run], items: list[dict[str, Any]], manifest: dict[str, Any]) -> list[str]:
    found = []
    for record in items:
        feature = record["feature"]
        found += [f"{feature}: check {item.get('name')} waived without --user-decision" for item in record.get("checks") or []
                  if item.get("result") == "waived" and not item.get("user_decision")]
        found += [f"{feature}: {item.get('id')} closed as not a bug without --user-decision" for item in record.get("bugs") or []
                  if item.get("status") == "closed_not_a_bug" and not item.get("user_decision")]
        found += [f"{feature}: {item.get('id')} deferred without --user-decision" for item in record.get("tool_gaps") or []
                  if item.get("status") == "deferred" and not item.get("user_decision")]
    for entry in manifest.get("history") or []:
        if not isinstance(entry, dict) or entry.get("action") != "edit" or entry.get("user_decision"):
            continue
        if entry.get("conflict") or entry.get("status_at_edit") in ("in_progress", "accepted"):
            found.append(f"{entry.get('specification')}: {entry.get('status_at_edit')} spec edited without --user-decision")
    for run in runs:
        if run.kind != "main":
            continue
        for call in run.calls:
            match = SPEC_FILE.search(call.path) if call.name in EDIT_TOOLS else None
            if match:
                found.append(f"parent edited specs/{match.group(1)} directly (no `spec edit` audit or user decision)")
    return list(dict.fromkeys(found))


def reused_scripts(measured: list[dict[str, Any]]) -> list[str]:
    runs_per_name: Counter = Counter(name for run in measured if run["kind"] == "subagent" for name in run["adhoc_scripts"]["names"])
    return [f"{name} written in {count} runs" for name, count in sorted(runs_per_name.items()) if count > 1]


def hand_written(runs: list[Run]) -> list[str]:
    return [f"{label(run)}" for run in runs if run.kind == "subagent" and run.role in ("planner", "implementer", "reviewer", "tester", "fixer", "toolsmith")
            and not run.brief]


def build(root: Path, runs: list[Run], measured: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items = records(root)
    manifest = read_json(root / "implementation" / "spec-archive.json") or {}
    return [
        check("deps.early-start", "Specs started before their dependencies were accepted", early_starts(root, items, manifest),
              "tracker init / handoff --to implementer (dependency start guard)"),
        check("lanes.outside", "Edits outside assigned paths (or by read-only roles)", outside_lanes(root, runs, items),
              "tracker assign + path-guard hook"),
        check("verifiers.non-fresh", "First review/test rounds by a non-fresh agent", non_fresh(runs), "spec-orchestrator: fresh verifiers"),
        check("decisions.no-user", "Parent decisions without a recorded user decision", missing_decisions(root, runs, items, manifest),
              "--user-decision on waive/close/defer/spec edit; hook denies direct spec edits"),
        check("tools.reused-throwaway", "Throwaway scripts rebuilt across rounds", reused_scripts(measured), "tool-gap + toolsmith"),
        check("prompts.not-brief", "Delegation prompts not generated by tracker brief", hand_written(runs), "tracker brief"),
    ]
