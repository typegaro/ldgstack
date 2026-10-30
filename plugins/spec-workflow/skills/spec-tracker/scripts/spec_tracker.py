#!/usr/bin/env python3
"""Manage specification implementation records under implementation/."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable

from tracker import brief as briefs
from tracker import deps, toolkit
from tracker import paths as lanes
from tracker import plan as plans
from tracker import requirements as spec_requirements
from tracker.model import (
    BUG_TRANSITIONS, CHECK_RESULTS, HANDOFFS, ROLES, SEVERITIES,
    bump_generation, find_item, gate_errors, generation, generation_has_work, invalidate_item, latest_checks, next_id, not_run_checks, now,
    open_blockers, open_questions, open_tool_gaps, parent_attested, parent_status, require_confirmation, require_role,
    review_skip_errors, spec_matches, touch,
)
from tracker.store import (
    TrackerError, digest, feature_name, find_root, load, load_all, project_lock, record_path, remove, save, spec_path,
)

Record = dict[str, Any]
BUG_FIELDS = ("spec_ref", "environment", "reproduction", "expected", "actual", "evidence")
GATES = ("ready-test", "acceptance")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage specification implementation records")
    parser.add_argument("--json", action="store_true", help="emit one compact JSON result")
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init", help="create the active record for a specification")
    init.add_argument("spec")
    init.add_argument("--title")
    init.add_argument("--parent-confirmed", action="store_true")
    init.add_argument("--user-decision", help="start before depends_on/amends are accepted (the user's words)")
    init.add_argument("--early", action="store_true",
                      help="start while every unaccepted dependency is in progress or startable; batches gate on `**Requires:**`, acceptance on all of them")
    status = commands.add_parser("status", help="summarize one or all active records")
    status.add_argument("feature", nargs="?")
    commands.add_parser("list", help="summarize all active records")

    requirement = group(commands, "requirement")
    add = command(requirement, "add", confirmed=True)
    add.add_argument("--spec-ref", required=True)
    add.add_argument("--verification", required=True)
    imported = command(requirement, "import", confirmed=True, help="add one requirement per R<n> bullet of the spec")
    imported.add_argument("--include-amended", action="store_true", help="no-op: requirements the spec replaces/amends/removes are imported by default")
    imported.add_argument("--exclude-amended", action="store_true", help="skip requirements the spec replaces/amends/removes (spec-sync keeps this choice)")
    command(requirement, "list")
    implemented = command(requirement, "implemented", item=True, confirmed=True)
    implemented.add_argument("--evidence", required=True)
    implemented.add_argument("--location", default="")
    implemented.add_argument("--evidence-from", metavar="CHECK", help="parent light path: an existing passed check covers it")
    tested = command(requirement, "tested", item=True, confirmed=True)
    tested.add_argument("--evidence", required=True)
    tested.add_argument("--evidence-from", metavar="CHECK", help="parent light path: an existing passed tester check covers it")

    command(group(commands, "file"), "add").add_argument("path")

    checks = group(commands, "check")
    check = command(checks, "add", confirmed=True)
    check.add_argument("--name", required=True)
    check.add_argument("--method", required=True)
    check.add_argument("--result", choices=CHECK_RESULTS, required=True)
    check.add_argument("--evidence", required=True)
    waive = command(checks, "waive", confirmed=True)
    waive.add_argument("name")
    waive.add_argument("--reason", required=True)
    waive.add_argument("--user-decision", required=True)

    bugs = group(commands, "bug")
    bug_add = command(bugs, "add")
    bug_add.add_argument("--title", required=True)
    bug_add.add_argument("--severity", choices=SEVERITIES, required=True)
    for name in BUG_FIELDS:
        bug_add.add_argument(f"--{name.replace('_', '-')}", required=True)
    command(bugs, "assign", item=True).add_argument("--fixer", required=True)
    fixed = command(bugs, "fixed", item=True)
    fixed.add_argument("--fix", required=True)
    fixed.add_argument("--regression", required=True)
    command(bugs, "verify", item=True).add_argument("--retest", required=True)
    command(bugs, "reopen", item=True).add_argument("--evidence", required=True)
    close = command(bugs, "close", item=True, confirmed=True)
    close.add_argument("--reason", required=True)
    close.add_argument("--user-decision", required=True)

    blockers = group(commands, "blocker")
    blocker_add = command(blockers, "add")
    blocker_add.add_argument("--summary", required=True)
    blocker_add.add_argument("--report", required=True)
    command(blockers, "resolve", item=True, confirmed=True).add_argument("--resolution", required=True)

    gaps = group(commands, "tool-gap")
    gap_add = command(gaps, "add", help="record a missing test capability (tester or reviewer)")
    gap_add.add_argument("--capability", required=True, help="taxonomy capability, e.g. fe.inspect or ext.mock.oauth")
    gap_add.add_argument("--requirement", action="append", required=True, metavar="REQ-x", help="requirement it blocks (repeatable)")
    gap_add.add_argument("--why", required=True, help="what cannot be tested without it")
    gap_add.add_argument("--parent-confirmed", action="store_true", help="parent fallback: record a gap from any role (e.g. a toolkit requirement routed to the toolsmith)")
    gap_resolve = gap_item(gaps, "resolve", "mark a gap resolved by a verified toolkit tool (toolsmith)")
    gap_resolve.add_argument("--tool", required=True)
    gap_resolve.add_argument("--evidence", default="", help="what the tool now covers")
    gap_defer = gap_item(gaps, "defer", "defer a gap with a recorded user decision (parent)")
    gap_defer.add_argument("--reason", required=True)
    gap_defer.add_argument("--user-decision", required=True)
    gap_defer.add_argument("--parent-confirmed", action="store_true")
    gap_list = gaps.add_parser("list", help="tool gaps of one or all active records")
    gap_list.add_argument("feature", nargs="?")
    gap_list.add_argument("--open", action="store_true", help="only open gaps")

    kit = group(commands, "toolkit")
    kit.add_parser("list", help="registered tools (stale = unverified since last change)").add_argument("--capability")
    kit.add_parser("summary", help="one line per tool, for delegation prompts")
    for name in ("add", "update"):
        tool = kit.add_parser(name, help=f"{name} a toolkit tool (toolsmith or implementer)")
        tool.add_argument("name")
        required = name == "add"
        tool.add_argument("--capability", action="append", required=required, help="taxonomy capability (repeatable; replaces the list on update)")
        tool.add_argument("--command", dest="entry", required=required, help="how agents invoke it")
        tool.add_argument("--location", required=required, help="project-relative path, e.g. be/cmd/fake-oauth or fe/tools/fe-drive")
        tool.add_argument("--smoke", required=required, help="smoke command run from the project root by toolkit verify")
        tool.add_argument("--owner-spec", required=required, help="spec that owns the tool, e.g. 0019")
        tool.add_argument("--mode", choices=toolkit.MODES, required=required)
        tool.add_argument("--guard", help="mutating tools: how it refuses the dev database unless explicitly targeted")
        tool.add_argument("--description")
    verify = kit.add_parser("verify", help="run smoke tests; fails if any fails")
    verify.add_argument("names", nargs="*")
    verify.add_argument("--timeout", type=int, default=toolkit.SMOKE_TIMEOUT)
    retire = kit.add_parser("remove", help="unregister a tool")
    retire.add_argument("name")
    retire.add_argument("--reason", required=True)

    handoff = command(commands, "handoff", confirmed=True)
    handoff.add_argument("--to", choices=ROLES, required=True)
    handoff.add_argument("--completed", help="required unless --question")
    handoff.add_argument("--remaining", help="required unless --question")
    handoff.add_argument("--checks-not-run", default="None")
    handoff.add_argument("--user-decision", help="to implementer before depends_on/amends are accepted (the user's words)")
    handoff.add_argument("--question", help="--to parent: ask the parent instead of improvising; sets needs_answer")
    handoff.add_argument("--reason", help="with --parent-confirmed: why the implementer may start without a plan")

    plan = group(commands, "plan")
    plan_add = command(plan, "add", confirmed=True, help="store a plan (planner, or parent) from a file or - for stdin")
    plan_add.add_argument("--from", dest="source", required=True, metavar="FILE|-")
    plan_show = command(plan, "show", help="print the latest plan, or one batch with its ownership")
    plan_show.add_argument("--batch", type=int, metavar="N")
    plan_show.add_argument("--version", type=int, metavar="V")
    answer = command(commands, "answer", help="answer the open question (parent); --replan routes to the planner")
    answer.add_argument("--text", required=True)
    answer.add_argument("--replan", action="store_true", help="design question: send the record to the planner")

    assign = command(commands, "assign", confirmed=True, help="set the paths the next agent for this record may edit (parent)")
    assign.add_argument("--role", choices=[role for role in ROLES if role != "parent"])
    lane = assign.add_mutually_exclusive_group()
    lane.add_argument("--paths", nargs="+", metavar="GLOB", help="project-relative globs (** crosses directories)")
    lane.add_argument("--read-only", action="store_true", help="the agent may edit nothing in the project")
    lane.add_argument("--release", action="store_true", help="end this record's active assignment")
    lane.add_argument("--from-plan", action="store_true", help="use the latest plan's ownership globs")
    assign.add_argument("--batch", type=int, metavar="N", help="with --from-plan on an early record: the plan batch the lane is for")
    assign.add_argument("--carve", action="append", metavar="GLOB", help="take this narrow glob out of another spec's active lane (--from) and grant it here (repeatable)")
    assign.add_argument("--from", dest="carve_from", metavar="ASSIGNMENT", help="with --carve: the other spec's active assignment that gives up the glob")
    assign.add_argument("--alongside", action="store_true",
                        help="--role toolsmith while the fixer works: keep the fixer's lane (lanes must be disjoint); the toolsmith ends with `join`")
    joined = command(commands, "join", help="end the side toolsmith's work alongside the fixer (the side agent's last command)")
    joined.add_argument("--completed", required=True)
    assign.add_argument("--user-decision", help="early record: run a batch before its required specs are accepted (the user's words, with --parent-confirmed)")
    commands.add_parser("claim", help="first command of a brief: binds this agent to its assignment (the hook records it)").add_argument("assignment")
    brief = command(commands, "brief", help="print the delegation prompt for the record's current role")
    brief.add_argument("--role", required=True, choices=[role for role in ROLES if role != "parent"])
    brief.add_argument("--batch", metavar="N|REQ-a..REQ-b", help="implementer batch: a plan batch number or a requirement range")
    brief.add_argument("--final-batch", action="store_true")
    brief.add_argument("--parent-confirmed", action="store_true", help="allow an unbatched or unplanned implementer brief")
    brief.add_argument("--user-decision", help="early record: brief a batch before its required specs are accepted (the user's words, with --parent-confirmed)")
    brief.add_argument("--fresh", action="store_true", help="release the role's active assignment and issue a new one (same paths) for a fresh agent; "
                       "automatic when an agent already claimed it")

    gate_parser = commands.add_parser("gate", help="gate <feature> ready-test|acceptance")
    gate_parser.add_argument("first", metavar="feature")
    gate_parser.add_argument("second", metavar="gate")
    overlap = commands.add_parser("overlap", help="changed files shared by active records")
    overlap.add_argument("--plans", action="store_true", help="compare planned ownership globs and active lanes instead of changed files")
    overlap.add_argument("--depth", type=int, default=0, help="compare the first N path components (0: whole paths)")
    command(commands, "spec-check")
    command(commands, "spec-sync", confirmed=True).add_argument("--reason", required=True)
    command(commands, "archive", confirmed=True)
    command(commands, "restore", confirmed=True)
    return parser


def group(commands: Any, name: str) -> Any:
    return commands.add_parser(name).add_subparsers(dest="action", required=True)


def command(parent: Any, name: str, item: bool = False, confirmed: bool = False, help: str | None = None) -> argparse.ArgumentParser:
    parser = parent.add_parser(name, help=help)
    parser.add_argument("feature")
    if item:
        parser.add_argument("id")
    if confirmed:
        parser.add_argument("--parent-confirmed", action="store_true")
    return parser


def gap_item(parent: Any, name: str, help: str) -> argparse.ArgumentParser:
    parser = parent.add_parser(name, help=help)
    parser.add_argument("first", metavar="feature|gap-id")
    parser.add_argument("second", metavar="gap-id", nargs="?")
    return parser


def summary(record: Record, root: Path | None = None) -> Record:
    requirements = record["requirements"]
    early: Record = {}
    if record.get("early"):
        waiting = deps.unaccepted(root, record.get("blocked_on") or []) if root is not None else list(record.get("blocked_on") or [])
        early = {"early": True, "blocked_on": record.get("blocked_on") or [], "blocked_on_pending": waiting}
    return {
        **early,
        "feature": record["feature"], "status": record["status"], "current_role": record["current_role"],
        **({"side_role": record["side_role"]} if record.get("side_role") else {}),
        "generation": generation(record),
        "requirements": {
            "total": len(requirements),
            "implemented": sum(item["implemented"] for item in requirements),
            "tested": sum(item["tested"] for item in requirements),
        },
        "bugs": {status: sum(item["status"] == status for item in record["bugs"]) for status in sorted({item["status"] for item in record["bugs"]})},
        "open_blockers": len(open_blockers(record)), "open_tool_gaps": len(open_tool_gaps(record)),
        "open_questions": [f"{item['id']} ({item['role']}): {item['text']}" for item in open_questions(record)],
        "plan_version": (plans.latest(record) or {}).get("version"),
        **({"plan_stale": plans.stale_text(plans.latest(record))} if plans.stale_text(plans.latest(record)) else {}),
        "checks_not_run": not_run_checks(record), "pending": pending_steps(record, root),
        "updated_at": record["updated_at"],
    }


def pending_steps(record: Record, root: Path | None) -> list[str]:
    """Bookkeeping the parent owes after a spec edit (`spec edit` changes the hash; spec-sync then needs an import)."""
    steps = []
    if root is not None and (root / record["specification"]["path"]).is_file() and not spec_matches(root, record):
        steps.append(f"tracker spec-sync {record['feature']} --reason \"...\" --parent-confirmed")
    if record.get("import_pending"):
        steps.append(f"tracker requirement import {record['feature']} --parent-confirmed")
    return steps


def edit(root: Path, feature: str, roles: set[str], change: Callable[[Record], None]) -> Record:
    record = load(root, feature)
    require_role(record, roles)
    change(record)
    touch(record)
    save(root, record)
    return summary(record, root)


def initialize(root: Path, args: argparse.Namespace) -> Record:
    spec = spec_path(root, args.spec)
    feature = feature_name(args.spec)
    if record_path(root, feature).exists():
        raise TrackerError("active implementation record already exists")
    if record_path(root, feature, archived=True).exists():
        raise TrackerError("record is archived; use restore to reopen it")
    timestamp = now()
    record = {
        "schema_version": 1, "managed_by": "spec_tracker.py", "feature": feature,
        "title": args.title or feature.replace("-", " ").title(),
        "specification": {"path": spec.relative_to(root).as_posix(), "sha256": digest(spec), "history": []},
        "status": "new", "current_role": "parent", "generation": 1,
        "created_at": timestamp, "updated_at": timestamp,
        "requirements": [], "changed_files": [], "checks": [], "bugs": [], "blockers": [],
        "handoff": {"completed": "", "remaining": "", "checks_not_run": "", "next_role": ""},
    }
    if spec.name in deps.deferred_names(root):
        raise TrackerError(f"{spec.name} is deferred; `spec undefer <id> --parent-confirmed` first")
    waiting = deps.pending(root, spec)
    if args.early and waiting and deps.early_startable(root, spec):
        record["early"], record["blocked_on"] = True, [deps.spec_id(name) for name in waiting]
    else:
        if args.early and waiting and not (args.parent_confirmed and args.user_decision):
            raise TrackerError(f"--early needs every unaccepted dependency ({', '.join(waiting)}) to be in progress or startable; "
                               f"otherwise only with the user's decision: --parent-confirmed --user-decision \"<the user's words>\"")
        start_guard(root, record, args.parent_confirmed, args.user_decision, "init")
    save(root, record)
    return summary(record, root)


def start_guard(root: Path, record: Record, confirmed: bool, decision: str | None, during: str) -> None:
    spec = root / record["specification"]["path"]
    if record.get("early") and {deps.spec_id(name) for name in deps.pending(root, spec)} <= set(record.get("blocked_on") or []):
        return  # early start: batches and acceptance gate on blocked_on instead
    try:
        deps.guard(root, record, root / record["specification"]["path"], confirmed, decision, during, now())
    except ValueError as error:
        raise TrackerError(str(error)) from error


REQUIREMENT_ROLES = {"add": {"parent"}, "import": {"parent"}, "implemented": {"implementer"}, "tested": {"tester"}}
# Roles whose passed check may back a parent-attested requirement (the light path).
ATTEST_ROLES = {"implemented": {"implementer", "fixer", "reviewer", "tester", "toolsmith"}, "tested": {"tester"}}


def parent_roles(confirmed: bool) -> set[str]:
    """With --parent-confirmed, the parent may add requirements while the record is in any role."""
    return set(ROLES) if confirmed else {"parent"}


def new_requirement(record: Record, spec_ref: str, verification: str, origin: str = "manual", origin_spec: int | None = None) -> Record:
    return {
        "id": next_id(record["requirements"] + record.get("retired_requirements", []), "REQ-"), "spec_ref": spec_ref,
        "implementation": "", "verification": verification,
        "implemented": False, "implementation_evidence": "", "tested": False, "test_evidence": "",
        "added_at": now(), "added_during_role": record["current_role"], "generation": generation(record),
        "origin": origin, **({"origin_spec": origin_spec} if origin_spec is not None else {}),
    }


def attest(record: Record, item: Record, action: str, check_name: str) -> None:
    require_role(record, {"parent"})
    latest = {entry["name"]: entry for entry in latest_checks(record)}.get(check_name)
    if latest is None or latest["result"] != "passed":
        raise TrackerError(f"--evidence-from needs a check whose latest result is passed: {check_name}")
    if latest.get("role") not in ATTEST_ROLES[action]:
        raise TrackerError(f"--evidence-from for {action} needs a check recorded by {', '.join(sorted(ATTEST_ROLES[action]))}")
    if action == "tested" and latest["at"] < item.get("implemented_at", ""):
        raise TrackerError("--evidence-from check ran before the requirement was implemented")
    item.setdefault("parent_attested", {})[action] = {"check": check_name, "check_role": latest["role"], "check_at": latest["at"], "at": now()}


def testability_tools(root: Path, item: Record, evidence: str) -> list[Record]:
    """A `## Testability` requirement is a reusable tool: the evidence names the registered toolkit tool (or the inspect tool)
    whose smoke passed, its smoke check, and its `--help`. One-off scripts and test procedures are not registered tools."""
    tools = toolkit.load(root)["tools"]
    named = [tool for tool in tools if re.search(rf"(?<![\w.-]){re.escape(tool['name'])}(?![\w-])", evidence)]
    example = (f'--evidence "tool <name> (`<invocation>`); --help documents it; smoke: toolkit verify <name> passed"; registered: '
               f"{', '.join(tool['name'] for tool in tools) or 'none'}")
    if not named:
        raise TrackerError(f"{item['id']} ({item['spec_ref']}) is a Testability requirement: the evidence must name the toolkit tool or "
                           f"inspect tool it added or changed and its smoke check; one-off scripts and test procedures don't count. Register it (`toolkit add|update`), run `toolkit verify <name>`, then {example}")
    stale = [tool["name"] for tool in named if toolkit.stale(tool)]
    if stale:
        raise TrackerError(f"{item['id']}: no passing smoke run since the last change of {', '.join(stale)}; run `toolkit verify {' '.join(stale)}` first")
    if not re.search(r"\b(smoke|verify)\b", evidence, re.IGNORECASE) or "--help" not in evidence:
        raise TrackerError(f"{item['id']}: name the smoke check and the tool's `--help` in the evidence too; {example}")
    return [{"name": tool["name"], "smoke": tool.get("smoke", ""), "verified_at": tool.get("verified_at", "")} for tool in named]


def requirement(root: Path, args: argparse.Namespace) -> Any:
    if args.action == "list":
        # Deliberately omits implementation evidence so testers can plan from the spec alone.
        return [
            {key: item[key] for key in ("id", "spec_ref", "verification", "implemented", "tested")}
            for item in load(root, args.feature)["requirements"]
        ]
    if args.action == "import":
        return import_requirements(root, args)
    light = args.action in ATTEST_ROLES and (args.parent_confirmed or args.evidence_from)
    if light and not (args.parent_confirmed and args.evidence_from):
        raise TrackerError("the parent light path needs both --parent-confirmed and --evidence-from <check>")

    def change(record: Record) -> None:
        if args.action == "add":
            if record["current_role"] != "parent":
                require_confirmation(args.parent_confirmed, f"adding a requirement while the record is with the {record['current_role']}")
            record["requirements"].append(new_requirement(record, args.spec_ref, args.verification))
            return
        item = find_item(record, "requirements", args.id)
        if light:
            attest(record, item, args.action, args.evidence_from)
        if args.action == "implemented":
            if item.get("testability"):
                item["testability_tools"] = testability_tools(root, item, args.evidence)
            if item.get("implemented") and any(entry.get("role") == "reviewer" for entry in latest_checks(record)):
                bump_generation(record, f"{item['id']} re-implemented")
            item.update(implemented=True, implementation_evidence=args.evidence, implemented_at=now(),
                        implemented_generation=generation(record), tested=False, test_evidence="")
            item.pop("tested_generation", None)
            if args.location:
                item["implementation"] = args.location
        elif not item["implemented"]:
            raise TrackerError("cannot test a requirement before it is implemented")
        else:
            item.update(tested=True, test_evidence=args.evidence, tested_at=now(), tested_generation=generation(record))

    roles = set(ROLES) if light else parent_roles(args.parent_confirmed) if args.action == "add" else REQUIREMENT_ROLES[args.action]
    return edit(root, args.feature, roles, change)


AMENDED_VERIFICATION = {
    "replaces": "Replaced by {source}: the replacement holds and the original no longer applies where replaced.",
    "amends": "Amended by {source}: re-verify it holds as amended.",
    "removes": "Removed by {source}: the removed behavior is gone.",
}


def spec_files(root: Path) -> dict[int, Path]:
    found: dict[int, Path] = {}
    for path in sorted((root / "specs").glob("*.md")):
        number = spec_requirements.spec_number(path)
        if number is not None:
            found.setdefault(number, path)
    return found


def import_candidates(root: Path, record: Record, include_amended: bool) -> tuple[list[tuple[str, str]], dict[str, str], list[str]]:
    """(spec_ref, verification text) per requirement, the citing requirement of each amended target, and warnings."""
    path = root / record["specification"]["path"]
    number = spec_requirements.spec_number(path)
    if number is None:
        raise TrackerError(f"cannot derive the spec number from {path.name}")
    parsed = spec_requirements.parse(path.read_text(encoding="utf-8"))
    warnings = [f"{number}:R{item.id} has no text; skipped" for item in parsed if not item.text]
    seen: set[str] = set()
    for item in parsed:
        if item.id in seen:
            warnings.append(f"duplicate requirement ID {number}:R{item.id}")
        seen.add(item.id)
    candidates = [(f"{number}:R{item.id}", item.text) for item in parsed if item.text]
    sources: dict[str, str] = {}
    if not include_amended:
        return candidates, sources, warnings
    files = spec_files(root)
    texts: dict[int, dict[str, str]] = {}
    for item in parsed:
        for reference in spec_requirements.references(item):
            if reference.spec not in texts:
                target = files.get(reference.spec)
                texts[reference.spec] = (
                    {entry.id: entry.text for entry in spec_requirements.parse(target.read_text(encoding="utf-8"))} if target else {}
                )
            original = texts[reference.spec].get(reference.requirement)
            if original is None:
                warnings.append(f"{number}:R{item.id} references {reference.ref}, which was not found; skipped")
                continue
            verification = AMENDED_VERIFICATION[reference.verb].format(source=f"{number}:R{item.id}")
            candidates.append((reference.ref, f"{verification} Original: {original}"))
            sources.setdefault(reference.ref, f"{number}:R{item.id}")
    return candidates, sources, warnings


def reconcile(root: Path, record: Record, include_amended: bool, sync: str | None = None) -> Record:
    """Bring the record's imported requirements in line with the spec. On spec-sync (`sync` = reason), requirements whose
    text changed (or whose citing requirement changed) lose their marks; unchanged ones keep marks and evidence (#44)."""
    result: Record = {"added": [], "updated": [], "changed": [], "retired": [], "skipped": [], "warnings": []}
    candidates, sources, warnings = import_candidates(root, record, include_amended)
    result["warnings"].extend(warnings)
    candidate_map = dict(candidates)
    existing = {item["spec_ref"]: item for item in record["requirements"]}
    current_spec = spec_requirements.spec_number(root / record["specification"]["path"])
    if current_spec is None:
        raise TrackerError("cannot reconcile requirements without a numbered specification")
    if record.get("import_pending") or sync:
        kept = []
        for item in record["requirements"]:
            structured = re.match(r"^([0-9]+):R", item["spec_ref"])
            imported = item.get("origin") == "imported" or (item.get("origin") is None and structured is not None)
            belongs = item.get("origin_spec") == current_spec or (structured is not None and int(structured.group(1)) == current_spec)
            in_scope = imported and (belongs or include_amended)
            if in_scope and item["spec_ref"] not in candidate_map:
                item.update(retired_at=now(), retired_generation=generation(record), retirement_reason="removed from effective specification")
                record.setdefault("retired_requirements", []).append(item)
                result["retired"].append(item["id"] + " " + item["spec_ref"])
            else:
                kept.append(item)
        record["requirements"] = kept
        existing = {item["spec_ref"]: item for item in kept}
    spec_text = (root / record["specification"]["path"]).read_text(encoding="utf-8")
    testable = {f"{current_spec}:R{rid}" for rid in spec_requirements.testability_ids(spec_text)}
    changed_refs = {ref for ref, text in candidates if ref in existing and existing[ref]["verification"] != text}
    for spec_ref, verification in candidates:
        if spec_ref in existing:
            existing[spec_ref]["testability"] = spec_ref in testable
            item = existing[spec_ref]
            if item["verification"] != verification:
                item["verification"] = verification
                result["updated"].append(item["id"] + " " + spec_ref)
            if sync and (spec_ref in changed_refs or sources.get(spec_ref) in changed_refs):
                invalidate_item(item, f"specification changed: {sync}", invalidate_implementation=True)
                result["changed"].append(item["id"] + " " + spec_ref)
            item.update(origin="imported", origin_spec=current_spec)
            result["skipped"].append(spec_ref)
            continue
        item = new_requirement(record, spec_ref, verification, "imported", current_spec)
        item["testability"] = spec_ref in testable
        record["requirements"].append(item)
        existing[spec_ref] = item
        result["added"].append(f"{item['id']} {spec_ref}")
    record.pop("import_pending", None)
    return result


def import_requirements(root: Path, args: argparse.Namespace) -> Record:
    found: Record = {}

    def change(record: Record) -> None:
        if not spec_matches(root, record):
            raise TrackerError("specification hash changed; run spec-sync before importing")
        if record["current_role"] != "parent":
            require_confirmation(args.parent_confirmed, f"importing requirements while the record is with the {record['current_role']}")
        # Amended targets are imported by default (#62), so a later spec-sync never pulls them in mid-run.
        if args.exclude_amended:
            record["exclude_amended"] = True
        else:
            record.pop("exclude_amended", None)
        found.update(reconcile(root, record, not args.exclude_amended))
        found.pop("changed")

    result = edit(root, args.feature, parent_roles(args.parent_confirmed), change)
    return {**result, **found}


def changed_file(root: Path, args: argparse.Namespace) -> Record:
    def change(record: Record) -> None:
        if args.path not in record["changed_files"]:
            record["changed_files"].append(args.path)

    return edit(root, args.feature, {"implementer", "fixer", "toolsmith"}, change)


def check(root: Path, args: argparse.Namespace) -> Record:
    superseded: Record = {}

    def add(record: Record) -> None:
        latest = {item["name"]: item for item in latest_checks(record)}.get(args.name)
        owner = next((item.get("role") for item in reversed(record["checks"])
                      if item["name"] == args.name and item.get("role") in {"reviewer", "tester"}), None)
        if owner is not None and record["current_role"] != owner:
            raise TrackerError(f"the {owner}'s check {args.name} may only be re-recorded by the {owner}; route it back: "
                               f"`tracker handoff {record['feature']} --to {owner} --completed \"...\" --remaining \"re-record {args.name}\"`")
        if record["current_role"] == "parent":
            require_confirmation(args.parent_confirmed, "recording a check as the parent")
            if latest is not None and latest.get("role") in {"reviewer", "tester"}:
                raise TrackerError(f"the parent cannot re-record the {latest['role']}'s check {args.name}; "
                                   f"route it back: `tracker handoff {record['feature']} --to {latest['role']} ...`")
        if latest is not None:
            # Same name supersedes: gates read only the latest result per name.
            superseded.update(superseded={"name": args.name, "result": latest["result"], "role": latest.get("role", "")})
        record["checks"].append({
            "name": args.name, "method": args.method, "result": args.result,
            "evidence": args.evidence, "role": record["current_role"], "generation": generation(record), "at": now(),
        })

    def waive(record: Record) -> None:
        require_confirmation(args.parent_confirmed, "waiving a check")
        latest = {item["name"]: item for item in latest_checks(record)}.get(args.name)
        if latest is None or latest["result"] != "not_run":
            raise TrackerError(f"only a check whose latest result is not_run can be waived: {args.name}")
        record["checks"].append({
            "name": args.name, "method": latest["method"], "result": "waived",
            "evidence": f"Waived: {args.reason}", "user_decision": args.user_decision, "role": "parent",
            "generation": generation(record), "at": now(),
        })

    if args.action == "waive":
        return edit(root, args.feature, {"parent"}, waive)
    return {**edit(root, args.feature, set(ROLES), add), **superseded}


def bug(root: Path, args: argparse.Namespace) -> Record:
    def add(record: Record) -> None:
        record["bugs"].append({
            "id": next_id(record["bugs"], f"BUG-{record['feature']}-"), "title": args.title,
            "status": "open", "severity": args.severity, "found_by": record["current_role"],
            **{name: getattr(args, name) for name in BUG_FIELDS},
            "assigned_fixer": "", "fix": "", "regression": "", "retest": "",
        })

    def transition(record: Record) -> None:
        item = find_item(record, "bugs", args.id)
        allowed = BUG_TRANSITIONS[args.action][1]
        if item["status"] not in allowed:
            raise TrackerError(f"cannot {args.action} bug in status {item['status']}")
        if args.action == "assign":
            item.update(status="assigned", assigned_fixer=args.fixer)
        elif args.action == "fixed":
            item.update(status="fixed", fix=args.fix, regression=args.regression)
        elif args.action == "verify":
            item.update(status="verified", retest=args.retest)
        elif args.action == "reopen":
            item.update(status="open", evidence=f"{item['evidence']} | Reopened: {args.evidence}", fix="", regression="", retest="")
        else:
            require_confirmation(args.parent_confirmed, "closing a bug as not a bug")
            item.update(status="closed_not_a_bug", retest=args.reason, user_decision=args.user_decision)

    if args.action == "add":
        return edit(root, args.feature, {"reviewer", "tester"}, add)
    return edit(root, args.feature, {BUG_TRANSITIONS[args.action][0]}, transition)


def blocker(root: Path, args: argparse.Namespace) -> Record:
    def add(record: Record) -> None:
        record["blockers"].append({
            "id": next_id(record["blockers"], f"BLOCKER-{record['feature']}-", "BLOCKER-"), "summary": args.summary,
            "report": args.report, "status": "open", "resolution": "",
        })

    def resolve(record: Record) -> None:
        require_confirmation(args.parent_confirmed, "resolving a specification blocker")
        item = find_item(record, "blockers", args.id)
        if item.get("status", "open") != "open":
            raise TrackerError(f"blocker is already resolved: {args.id}")
        item.update(status="resolved", resolution=args.resolution, resolved_during_role=record["current_role"])

    if args.action == "add":
        return edit(root, args.feature, {"implementer", "reviewer", "tester", "fixer", "toolsmith"}, add)
    return edit(root, args.feature, set(ROLES), resolve)


def gap_target(args: argparse.Namespace) -> tuple[str, str]:
    if args.second:
        return args.first, args.second
    match = re.fullmatch(r"GAP-(.+)-([0-9]{3,})", args.first)
    if not match:
        raise TrackerError("pass <feature> <gap-id>, or a fully qualified GAP-<feature>-NNN")
    return match.group(1), args.first


def tool_gap(root: Path, args: argparse.Namespace) -> Any:
    if args.action == "list":
        records = [load(root, args.feature)] if args.feature else load_all(root)
        return [
            {"feature": record["feature"], **item} for record in records for item in record.get("tool_gaps", [])
            if not args.open or item["status"] == "open"
        ]
    if args.action == "add":
        wanted = toolkit.capability(args.capability)

        def add(record: Record) -> None:
            known = {item["id"] for item in record["requirements"]}
            unknown = sorted(set(args.requirement) - known)
            if unknown:
                raise TrackerError(f"unknown requirement ID: {', '.join(unknown)}")
            gaps = record.setdefault("tool_gaps", [])
            gaps.append({
                "id": next_id(gaps, f"GAP-{record['feature']}-"), "capability": wanted, "requirements": sorted(set(args.requirement)),
                "why": args.why, "status": "open", "found_by": "parent" if args.parent_confirmed else record["current_role"],
                "added_at": now(), "tool": "", "resolution": "",
                **({"recorded_during_role": record["current_role"]} if args.parent_confirmed else {}),
            })

        return edit(root, args.feature, set(ROLES) if args.parent_confirmed else {"reviewer", "tester"}, add)
    feature, gap_id = gap_target(args)

    def resolve(record: Record) -> None:
        item = find_item(record, "tool_gaps", gap_id)
        if item["status"] != "open":
            raise TrackerError(f"tool gap is already {item['status']}: {gap_id}")
        tool = toolkit.find(toolkit.load(root), args.tool)
        if not toolkit.provides(tool, item["capability"]):
            raise TrackerError(f"{args.tool} does not provide {item['capability']}; add the capability with toolkit update")
        if toolkit.stale(tool):
            raise TrackerError(f"{args.tool} has no passing smoke run since its last change; run toolkit verify {args.tool}")
        item.update(status="resolved", tool=args.tool, resolution=args.evidence, resolved_at=now())

    def defer(record: Record) -> None:
        require_confirmation(args.parent_confirmed, "deferring a tool gap")
        item = find_item(record, "tool_gaps", gap_id)
        if item["status"] != "open":
            raise TrackerError(f"tool gap is already {item['status']}: {gap_id}")
        item.update(status="deferred", resolution=f"Deferred: {args.reason}", user_decision=args.user_decision,
                    resolved_at=now(), resolved_during_role=record["current_role"])
        if record["current_role"] == "parent":
            record["status"] = parent_status(root, record)

    if args.action == "resolve":
        return edit(root, feature, {"toolsmith"}, resolve)
    return edit(root, feature, set(ROLES), defer)


def toolkit_command(root: Path, args: argparse.Namespace) -> Any:
    if args.action == "list":
        return toolkit.listing(root, toolkit.capability(args.capability) if args.capability else None)
    if args.action == "summary":
        return toolkit.summary(root)
    if args.action == "add":
        return toolkit.add(root, args, now())
    if args.action == "update":
        return toolkit.update(root, args, now())
    if args.action == "remove":
        return toolkit.remove(root, args)
    result = toolkit.verify(root, args.names, args.timeout, now())
    if result["failed"]:
        tails = "; ".join(f"{item['name']}: {item.get('output_tail', '')}" for item in result["results"] if not item["passed"])
        raise TrackerError(f"toolkit smoke failed: {tails}")
    return result


READ_ONLY_ROLES = ("planner", "tester")  # handoff creates their read-only assignment when none is active


def auto_assign(record: Record, role: str) -> None:
    """A read-only lane for the planner or tester, so their brief always has an active assignment."""
    items = record.setdefault("assignments", [])
    if any(item["status"] == "active" and item["role"] == role for item in items):
        return
    for item in items:
        if item["status"] == "active":
            item.update(status="released", released_at=now())
    items.append({"id": next_id(items, f"ASSIGN-{record['feature']}-"), "role": role, "paths": [], "status": "active",
                  "at": now(), "auto": True})


def plan_guard(record: Record, args: argparse.Namespace) -> None:
    """The implementer (executor) starts from a plan once a spec is more than trivial."""
    if plans.latest(record) or not plans.needs_plan(record):
        return
    if args.parent_confirmed and args.reason:
        record["plan_waiver"] = {"reason": args.reason, "at": now()}
        return
    if record.get("plan_waiver"):
        return
    size = f"{len(record['requirements'])} requirements, areas: {', '.join(sorted(plans.areas(record))) or 'unknown'}"
    raise TrackerError(f"a plan is required before implementation ({size}): `tracker handoff {record['feature']} --to planner "
                       f'--completed "..." --remaining "plan it"`, then `tracker plan add`; or skip it with '
                       f'`--parent-confirmed --reason "..."`')


def ask(record: Record, args: argparse.Namespace) -> None:
    source = record["current_role"]
    if args.to != "parent" or source == "parent":
        raise TrackerError("--question goes from a subagent role to the parent: `handoff <feature> --to parent --question \"...\"`")
    questions = record.setdefault("questions", [])
    questions.append({"id": next_id(questions, f"Q-{record['feature']}-"), "role": source, "text": args.question,
                      "status": "open", "resume_status": record["status"], "at": now(), "answer": ""})
    record["current_role"] = "parent"
    record["status"] = "needs_answer"
    record["handoff"] = {"from": source, "completed": args.completed or "", "remaining": args.remaining or f"Question: {args.question}",
                         "checks_not_run": args.checks_not_run, "next_role": "parent"}


def handoff(root: Path, args: argparse.Namespace) -> Record:
    if not args.question and not (args.completed and args.remaining):
        raise TrackerError("handoff needs --completed and --remaining (or --to parent --question \"...\")")

    def change(record: Record) -> None:
        source, target = record["current_role"], args.to
        first_look = source == target == "parent" and record["status"] == "new"  # old flow: init, then handoff --to parent
        replan = (source, target) == ("implementer", "planner") and args.parent_confirmed and not any(item["implemented"] for item in record["requirements"])
        if target not in HANDOFFS[source] and not first_look and not replan:
            raise TrackerError(f"{source} cannot hand off to {target}; allowed: {', '.join(sorted(HANDOFFS[source]))}")
        if args.question:
            ask(record, args)
            return
        if record.get("side_role") and target != "parent":
            raise TrackerError(f"the {record['side_role']} still works alongside the {source}; it runs "
                               f"`tracker join {record['feature']} --completed \"...\"` first (joined before review and retest)")
        if source == "planner" and not plans.latest(record):
            raise TrackerError(f"no plan stored; run `tracker plan add {record['feature']} --from - <<'PLAN' ... PLAN` first")
        review_skipped = source == "implementer" and target == "tester"
        if review_skipped:
            skip_errors = review_skip_errors(record)
            if skip_errors:
                raise TrackerError("implementer cannot hand off to tester: " + "; ".join(skip_errors) + "; hand off to reviewer")
        gaps = [item["id"] for item in open_tool_gaps(record)]
        if target == "tester" and gaps:
            raise TrackerError(f"open tool gaps: {', '.join(gaps)}; hand off to parent to dispatch the toolsmith")
        if target == "tester" and not review_skipped and not any(
            item["result"] == "passed" and item.get("role") == "reviewer" for item in latest_checks(record)
        ):
            raise TrackerError("tester handoff requires a passing reviewer check in the current implementation generation")
        if target in {"reviewer", "tester"}:
            if source in {"fixer", "reviewer"} and any(item["status"] in {"open", "assigned"} for item in record["bugs"]):
                raise TrackerError(f"{source} cannot hand off to {target} while bugs are open or assigned; hand off to parent")
            # A role re-records its own failed checks after receiving the record (#17, #39).
            errors = gate_errors(root, record, "ready-test", exempt_roles=("tester", target))
            if errors:
                raise TrackerError("handoff blocked: " + "; ".join(errors))
            if target == "reviewer":
                record["status"] = "ready_for_review"
            else:
                retest = any(item["status"] == "fixed" for item in record["bugs"])
                record["status"] = "ready_for_retest" if retest else "ready_for_test"
        elif target == "fixer":
            if not any(item["status"] == "assigned" for item in record["bugs"]):
                raise TrackerError("no assigned bugs for fixer")
            if generation_has_work(record):
                bump_generation(record, "fixer started a code revision")
            record["status"] = "fixing"
        elif target == "implementer":
            start_guard(root, record, args.parent_confirmed, args.user_decision, "handoff")
            plan_guard(record, args)
            record["status"] = "implementing"
        elif target == "planner":
            record["status"] = "planning"
        elif target == "toolsmith":
            if not gaps:
                raise TrackerError("no open tool gaps for toolsmith")
            record["status"] = "tooling"
        if source != target and source in {"implementer", "fixer", "toolsmith"}:
            # A finished writer frees its lane so parallel specs can claim those paths (#51).
            for item in record.get("assignments", []):
                if item["status"] == "active" and item["role"] == source:
                    item.update(status="released", released_at=now(), released_by="handoff")
        if target in READ_ONLY_ROLES:
            auto_assign(record, target)
        record["current_role"] = target
        if target == "parent":
            record["status"] = parent_status(root, record)
        record["handoff"] = {
            "from": source, "completed": args.completed, "remaining": args.remaining,
            "checks_not_run": args.checks_not_run, "next_role": target,
        }
        if review_skipped:
            record["handoff"]["review_skipped"] = True

    return edit(root, args.feature, set(ROLES), change)


def answer(root: Path, args: argparse.Namespace) -> Record:
    def change(record: Record) -> None:
        pending = open_questions(record)
        if not pending:
            raise TrackerError("no open question; to replan without one, `tracker handoff <feature> --to planner ...`")
        item = pending[-1]
        target = "planner" if args.replan else item["role"]
        item.update(status="answered", answer=args.text, replan=args.replan, answered_at=now())
        record["current_role"] = target
        record["status"] = "planning" if args.replan else item.get("resume_status") or "implementing"
        if target in READ_ONLY_ROLES:
            auto_assign(record, target)
        record["handoff"] = {"from": "parent", "completed": f"Answered {item['id']}", "remaining": args.text,
                             "checks_not_run": record["handoff"].get("checks_not_run", ""), "next_role": target}

    return edit(root, args.feature, {"parent"}, change)


def read_source(source: str) -> str:
    if source == "-":
        return sys.stdin.read()
    try:
        return Path(source).read_text(encoding="utf-8")
    except OSError as error:
        raise TrackerError(f"cannot read plan file: {error}") from error


def plan_command(root: Path, args: argparse.Namespace) -> Any:
    if args.action == "show":
        record = load(root, args.feature)
        stored = record.get("plans") or []
        if not stored:
            raise TrackerError(f"no plan stored for {record['feature']}")
        chosen = stored[-1] if args.version is None else next((item for item in stored if item["version"] == args.version), None)
        if chosen is None:
            raise TrackerError(f"no plan version {args.version}; versions: {', '.join(str(item['version']) for item in stored)}")
        return plans.brief_text(chosen, args.batch, f"tracker plan show {record['feature']}") + "\n"
    text = read_source(args.source)
    result: Record = {}

    def change(record: Record) -> None:
        if record["current_role"] not in {"planner", "parent"}:
            require_confirmation(args.parent_confirmed, f"storing a plan while the record is with the {record['current_role']}")
        parsed, warnings = plans.parse(text, [item["id"] for item in record["requirements"]])
        stored = record.setdefault("plans", [])
        version = len(stored) + 1
        stored.append({"version": version, "generation": generation(record), "added_by": record["current_role"], "at": now(), **parsed})
        result.update(plan_version=version, batches=[f"{item['number']}: {', '.join(item['requirements'])}" for item in parsed["batches"]],
                      ownership=parsed["ownership"], warnings=warnings)

    return {**edit(root, args.feature, set(ROLES), change), **result}


def gate_arguments(args: argparse.Namespace) -> tuple[str, str]:
    if args.second in GATES:
        return args.first, args.second
    if args.first in GATES:
        print("warning: `gate <gate> <feature>` is deprecated; use `gate <feature> <gate>`", file=sys.stderr)
        return args.second, args.first
    raise TrackerError(f"gate must be one of {', '.join(GATES)}")


def gate(root: Path, args: argparse.Namespace) -> Record:
    feature, name = gate_arguments(args)
    record = load(root, feature)
    errors = gate_errors(root, record, name)
    if errors:
        raise TrackerError(f"{name} gate failed: " + "; ".join(errors))
    result: Record = {"feature": record["feature"], "gate": name, "passed": True}
    attested = parent_attested(record)
    if attested:
        result["parent_attested"] = attested
    not_applicable = [item["name"] for item in latest_checks(record) if item["result"] == "not_applicable"]
    if not_applicable:
        result["checks_not_applicable"] = not_applicable
    return result


def planned_globs(record: Record) -> list[str]:
    """Ownership of the record's latest plan (any generation) plus the paths of its active assignments."""
    stored = record.get("plans") or []
    globs = list((plans.latest(record) or (stored[-1] if stored else {})).get("ownership") or [])
    globs += [glob for item in record.get("assignments", []) if item["status"] == "active" for glob in item.get("paths") or []]
    return list(dict.fromkeys(globs))


def overlap_plans(root: Path) -> list[Record]:
    """Pairs of active records whose planned or assigned globs may select the same files (approximate: literal prefixes)."""
    records = [(record["feature"], planned_globs(record)) for record in load_all(root)]
    shared = []
    for index, (feature, globs) in enumerate(records):
        for other, other_globs in records[index + 1:]:
            pairs = list(dict.fromkeys(f"{left} <-> {right}" for left, right in lanes.overlap(globs, other_globs)))
            if pairs:
                shared.append({"features": [feature, other], "globs": pairs})
    return shared


def overlap(root: Path, args: argparse.Namespace) -> list[Record]:
    if args.plans:
        return overlap_plans(root)
    def area(path: str) -> str:
        parts = Path(path).parts
        return "/".join(parts[: args.depth] if args.depth > 0 else parts)

    records = [(record["feature"], {area(path) for path in record["changed_files"]}) for record in load_all(root)]
    shared = []
    for index, (feature, areas) in enumerate(records):
        for other, other_areas in records[index + 1:]:
            common = sorted(areas & other_areas)
            if common:
                shared.append({"features": [feature, other], "paths": common})
    return shared


def spec_check(root: Path, args: argparse.Namespace) -> Record:
    record = load(root, args.feature)
    if not spec_matches(root, record):
        raise TrackerError("specification hash changed")
    return {"feature": record["feature"], "specification_unchanged": True}


def imported_requirements(record: Record) -> bool:
    return any(item.get("origin") == "imported" for item in record["requirements"])


def spec_sync(root: Path, args: argparse.Namespace) -> Record:
    found: Record = {}

    def change(record: Record) -> None:
        require_confirmation(args.parent_confirmed, "spec-sync")
        specification = record["specification"]
        current = digest(root / specification["path"])
        if current == specification["sha256"]:
            raise TrackerError("specification is unchanged; nothing to sync")
        entry = {"previous_sha256": specification["sha256"], "sha256": current, "reason": args.reason, "at": now()}
        specification.setdefault("history", []).append(entry)
        specification["sha256"] = current
        if not imported_requirements(record) or record.get("import_pending"):
            # Hand-added requirements can't be diffed against the spec: invalidate everything, then `requirement import`.
            record["import_pending"] = True
            bump_generation(record, f"specification changed: {args.reason}", invalidate_implementation=True)
            return
        found.update(reconcile(root, record, not record.get("exclude_amended"), sync=args.reason))
        entry.update(changed=found["changed"], added=found["added"], retired=found["retired"])
        touched = [line.split(" ", 1)[0] for line in found["changed"] + found["added"] + found["retired"]]
        plan = plans.latest(record, any_generation=True)
        if plan and touched:
            plans.mark_stale(plan, touched, args.reason, now())
        if record["current_role"] == "parent":
            record["status"] = parent_status(root, record)
        found.pop("updated")
        found.pop("skipped")

    return {**edit(root, args.feature, {"parent"}, change), **found}


def archive(root: Path, args: argparse.Namespace) -> Record:
    record = load(root, args.feature)
    require_role(record, {"parent"})
    require_confirmation(args.parent_confirmed, "archive")
    errors = gate_errors(root, record, "acceptance")
    if errors:
        raise TrackerError("archive blocked: " + "; ".join(errors))
    if record_path(root, record["feature"], archived=True).exists():
        raise TrackerError("archived implementation record already exists")
    record.update(status="accepted", current_role="parent")
    for item in record.get("assignments", []):
        if item["status"] == "active":
            item.update(status="released", released_at=now())
    touch(record)
    save(root, record, archived=True)
    remove(root, record["feature"])
    return {"feature": record["feature"], "archived": True}


def restore(root: Path, args: argparse.Namespace) -> Record:
    require_confirmation(args.parent_confirmed, "restore")
    if record_path(root, args.feature).exists():
        raise TrackerError("active implementation record already exists")
    record = load(root, args.feature, archived=True)
    bump_generation(record, "accepted implementation restored", invalidate_implementation=True)
    record.update(status="implementing", current_role="parent")
    record["handoff"] = {
        "from": "parent", "completed": "Previous acceptance reopened",
        "remaining": "Reimplementation and independent retest", "checks_not_run": "", "next_role": "implementer",
    }
    touch(record)
    save(root, record)
    remove(root, record["feature"], archived=True)
    return summary(record, root)


def early_gate(root: Path, record: Record, candidates: list[Record | None], confirmed: bool, decision: str | None, during: str) -> Record | None:
    """An early record may run a batch only when the specs it requires are accepted (any candidate batch suffices).
    Returns the override to store when the parent overrides with the user's decision, else None."""
    if not record.get("early"):
        return None
    blocked = [deps.blocked_batch(record, item, root) for item in candidates]
    if any(not item for item in blocked):
        return None
    waiting = sorted({name for item in blocked for name in item})
    if confirmed and decision and decision.strip():
        return {"pending": waiting, "user_decision": decision, "during": during, "at": now()}
    raise TrackerError(f"early start: {record['feature']} still requires unaccepted specs {', '.join(waiting)} for this batch; run a batch marked "
                       f"`**Requires:** none` or one whose required specs are accepted, or (user decision only) --parent-confirmed --user-decision \"<the user's words>\"")


def plan_batches(record: Record, number: int | None, whole: bool) -> list[Record | None]:
    """The batches a lane or brief covers: the named one, else every batch (`whole`: it runs them all, a single-batch plan counts as its batch)."""
    plan = plans.latest(record)
    if plan is None:
        return [None]
    if number is not None:
        return [plans.batch(plan, number)]
    return [plan["batches"][0]] if whole and len(plan["batches"]) == 1 else [None] if whole else list(plan["batches"])


def overlap_error(root: Path, clashes: list[tuple[str, Record, str]], feature: str, role: str, tracker: str) -> TrackerError:
    """Name every overlapping pair, the narrowest non-overlapping globs that exist on disk, and a carve-out (#64)."""
    taken = sorted({glob for other in lanes.active_assignments(root) if other["feature"] != feature for glob in other.get("paths") or []})
    lines = [f"{ours} overlaps {theirs} in {other['id']} ({other['feature']}, {other['role']})" for ours, other, theirs in clashes]
    for ours in dict.fromkeys(ours for ours, _, _ in clashes):
        narrow = lanes.narrower(root, ours, taken)
        if narrow:
            lines.append(f"non-overlapping globs under {ours}: {' '.join(narrow)}")
    for ours, other, theirs in clashes:
        if lanes.covers(theirs, ours):
            lines.append(f"or take {ours} from {other['id']}: `{tracker} assign {feature} --role {role} --carve {ours} --from {other['id']} --parent-confirmed`")
    return TrackerError("paths overlap another active lane: " + "; ".join(dict.fromkeys(lines))
                        + f"; narrow --paths, or finish that spec first (`{tracker} assign <feature> --release --parent-confirmed`)")


def assign(root: Path, args: argparse.Namespace) -> Record:
    tracker = "spec-tracker"
    if not (args.paths or args.read_only or args.release or args.from_plan or args.carve):
        raise TrackerError("one of --paths, --read-only, --release, --from-plan, or --carve is required")
    if not args.release and not args.role:
        raise TrackerError(f"--role is required; e.g. `{tracker} assign {args.feature} --role implementer --paths be/internal/chat/** --parent-confirmed`")
    if bool(args.carve) != bool(args.carve_from) or (args.carve and (args.read_only or args.release)):
        raise TrackerError("--carve GLOB needs --from ASSIGNMENT (the other spec's active lane) and grants paths, so not with --read-only or --release")
    override = None
    try:
        if args.from_plan:
            # Fix rounds bump the generation; fixers and toolsmiths keep the plan's ownership.
            latest_plan = plans.latest(load(root, args.feature), any_generation=args.role in ("fixer", "toolsmith"))
            if latest_plan is None:
                raise TrackerError(f"no plan stored for {args.feature}; `{tracker} plan add {args.feature} --from <file>` first")
            globs = list(latest_plan["ownership"])
            if args.role == "implementer":
                record = load(root, args.feature)
                override = early_gate(root, record, plan_batches(record, args.batch, False), args.parent_confirmed, args.user_decision, "assign")
        else:
            globs = [lanes.validate(item) for item in args.paths or []]
        carves = [lanes.validate(item) for item in args.carve or []]
    except ValueError as error:
        raise TrackerError(str(error)) from error
    globs = list(dict.fromkeys(globs + carves))
    result: dict[str, Any] = {}

    def change(record: Record) -> None:
        require_confirmation(args.parent_confirmed, "assigning paths")
        if override:
            record.setdefault("dependency_overrides", []).append(override)
        items = record.setdefault("assignments", [])
        side = record.get("side_role")
        if args.alongside:
            alongside_guard(record, args.role)
        for item in items:
            # The side lane survives a reassignment of the main role (and vice versa with --alongside); --release ends both.
            keep = not args.release and (args.alongside or (side and item["role"] == side))
            if item["status"] == "active" and not keep:
                item.update(status="released", released_at=now())
        if args.release:
            record.pop("side_role", None)
            return
        others = [other for other in lanes.active_assignments(root) if other["feature"] != record["feature"]]
        if args.alongside:
            mine = [item for item in items if item["status"] == "active"]
            shared = [f"{ours} overlaps {theirs} ({item['id']})" for item in mine for ours, theirs in lanes.overlap(globs, item.get("paths") or [])]
            if shared:
                raise TrackerError("--alongside needs a lane disjoint from the fixer's: " + "; ".join(shared))
            record["side_role"] = args.role
        source = None
        if carves:
            source = next((other for other in others if other["id"] == args.carve_from), None)
            if source is None:
                raise TrackerError(f"--from {args.carve_from} is not another spec's active assignment")
            wide = [glob for glob in carves if not any(lanes.covers(path, glob) for path in source.get("paths") or [])]
            if wide:
                raise TrackerError(f"--carve {', '.join(wide)} is not inside {source['id']}'s lane ({', '.join(source.get('paths') or [])}); carve a narrower glob")
        clashes = [
            (ours, other, theirs) for other in others for ours, theirs in lanes.lane_overlap(globs, other)
            if not (other is source and any(lanes.covers(glob, ours) for glob in carves))
        ]
        if clashes:
            raise overlap_error(root, clashes, record["feature"], args.role, tracker)
        item = {"id": next_id(items, f"ASSIGN-{record['feature']}-"), "role": args.role, "paths": globs, "status": "active", "at": now(),
                **({"alongside": True} if args.alongside else {})}
        if source is not None:
            item["carved_from"] = [{"glob": glob, "from": source["id"], "feature": source["feature"]} for glob in carves]
            carve(root, source, carves, item["id"], record["feature"])
        items.append(item)
        result.update(assignment=item["id"], role=args.role, paths=globs, claim=f"{tracker} claim {item['id']}")
        if source is not None:
            result["carved"] = f"{', '.join(carves)} from {source['id']} ({source['feature']}); its agent's writes there now warn"

    return {**edit(root, args.feature, set(ROLES), change), **result}


def alongside_guard(record: Record, role: str) -> None:
    """#52: the toolsmith may build tools for open gaps while the fixer fixes bugs, on a disjoint lane."""
    if role != "toolsmith" or record["current_role"] != "fixer":
        raise TrackerError("--alongside runs a toolsmith beside an active fixer: the record must be with the fixer and --role toolsmith")
    if not open_tool_gaps(record):
        raise TrackerError("no open tool gaps for a toolsmith")
    if record.get("side_role"):
        raise TrackerError(f"a {record['side_role']} already works alongside; it runs `join` first")


def join(root: Path, args: argparse.Namespace) -> Record:
    """The side toolsmith's last command: release its lane and log what it built; the fixer's handoff then proceeds."""
    def change(record: Record) -> None:
        side = record.get("side_role")
        if not side:
            raise TrackerError("no side role is working alongside; use `handoff`")
        for item in record.get("assignments", []):
            if item["status"] == "active" and item["role"] == side:
                item.update(status="released", released_at=now(), released_by="join")
        record.setdefault("side_handoffs", []).append({"role": side, "completed": args.completed, "at": now(),
                                                       "open_tool_gaps": [item["id"] for item in open_tool_gaps(record)]})
        record.pop("side_role")

    return edit(root, args.feature, set(ROLES), change)


def carve(root: Path, source: Record, globs: list[str], target: str, feature: str) -> None:
    """Record the carve-out on the giving lane; the hook and its brief then exclude those globs."""
    record = load(root, source["feature"])
    item = next(entry for entry in record.get("assignments", []) if entry["id"] == source["id"])
    item.setdefault("carved", []).extend({"glob": glob, "to": target, "feature": feature, "at": now()} for glob in globs)
    touch(record)
    save(root, record)


def claim_assignment(root: Path, args: argparse.Namespace) -> Record:
    for item in lanes.active_assignments(root):
        if item.get("id") == args.assignment:
            return {"assignment": item["id"], "feature": item["feature"], "role": item["role"], "paths": item.get("paths", []),
                    "note": "the path-guard hook binds this agent to the assignment and denies writes outside its paths"}
    raise TrackerError(f"unknown or released assignment {args.assignment}; ask the parent for a fresh brief")


def fresh_assignment(root: Path, args: argparse.Namespace, reason: str = "brief --fresh") -> None:
    """A fresh agent (e.g. the next batch's executor) gets its own assignment: same paths, new ID to claim."""
    def change(record: Record) -> None:
        if args.role not in (record["current_role"], record.get("side_role")):
            raise TrackerError(f"the record is with the {record['current_role']}; run `handoff {record['feature']} --to {args.role} ...` first")
        items = record.setdefault("assignments", [])
        active = [item for item in items if item["status"] == "active" and item["role"] == args.role]
        latest_plan = plans.latest(record)
        carved: list[Record] = []
        if active:
            paths = list(active[-1]["paths"])
            live = {item["id"] for item in lanes.active_assignments(root)}
            carved = [entry for entry in active[-1].get("carved", []) if entry["to"] in live]
        elif args.role in ("implementer", "fixer") and latest_plan:
            paths = list(latest_plan["ownership"])
        elif args.role in READ_ONLY_ROLES or args.role == "reviewer":
            paths = []
        else:
            raise TrackerError(f"no {args.role} assignment to renew; run `spec-tracker assign {record['feature']} --role {args.role} --paths ... --parent-confirmed`")
        for item in active:
            item.update(status="released", released_at=now(), released_by=reason)
        items.append({"id": next_id(items, f"ASSIGN-{record['feature']}-"), "role": args.role, "paths": paths, "status": "active", "at": now(), "fresh": True,
                      **({"carved": carved} if carved else {})})

    edit(root, args.feature, set(ROLES), change)


def brief(root: Path, args: argparse.Namespace) -> str:
    record = load(root, args.feature)
    if args.role == "implementer":
        number = briefs.plan_batch(record, args.batch)
        override = early_gate(root, record, plan_batches(record, number, True), args.parent_confirmed, args.user_decision, "brief")
        if override:
            edit(root, args.feature, set(ROLES), lambda item: item.setdefault("dependency_overrides", []).append(override))
    if args.fresh:
        fresh_assignment(root, args)
    elif args.role in (record["current_role"], record.get("side_role")):
        # Every brief starts a new agent (a resumed agent keeps its claim), so a claimed assignment is reissued (#46, #63).
        held = [item["id"] for item in record.get("assignments", []) if item["status"] == "active" and item["role"] == args.role]
        if held and lanes.claimed(root, held[-1]):
            fresh_assignment(root, args, "brief: claimed by an earlier agent")
            print(f"warning: {held[-1]} was claimed by an earlier agent; issued a new assignment with the same paths for this brief. "
                  "To continue the earlier agent instead, resume it with SendMessage (no new brief).", file=sys.stderr)
    record = load(root, args.feature)
    stale = plans.stale_text(plans.latest(record))
    if stale and args.role in ("implementer", "fixer", "reviewer"):
        print(f"warning: {stale}", file=sys.stderr)
    others = [item for item in lanes.active_assignments(root) if item["feature"] != record["feature"]]
    return briefs.render(root, record, args.role, args.batch, args.final_batch, others, args.parent_confirmed)


def status(root: Path, args: argparse.Namespace) -> Any:
    if getattr(args, "feature", None):
        return summary(load(root, args.feature), root)
    return [summary(record, root) for record in load_all(root)]


HANDLERS: dict[str, Callable[[Path, argparse.Namespace], Any]] = {
    "init": initialize, "status": status, "list": status, "requirement": requirement, "file": changed_file,
    "check": check, "bug": bug, "blocker": blocker, "handoff": handoff, "gate": gate,
    "spec-check": spec_check, "spec-sync": spec_sync, "archive": archive, "restore": restore, "overlap": overlap,
    "tool-gap": tool_gap, "toolkit": toolkit_command, "assign": assign, "claim": claim_assignment, "brief": brief,
    "plan": plan_command, "answer": answer, "join": join,
}


def output(value: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps({"ok": True, "result": value}, separators=(",", ":")))
    elif isinstance(value, str):
        print(value, end="")
    elif isinstance(value, list):
        for item in value:
            if "status" in item and "current_role" in item:
                early = f" [early, waiting on {', '.join(item['blocked_on_pending'])}]" if item.get("blocked_on_pending") else ""
                print(f"{item['feature']}: {item['status']} ({item['current_role']}){early}")
            else:
                print(" | ".join(f"{key}: {field}" for key, field in item.items()))
    elif "lines" in value:
        print(f"tools: {value['tools']}; stale: {', '.join(value['stale']) or 'none'}")
        for line in value["lines"]:
            print(line)
    elif "status" in value and "current_role" in value:
        print(f"{value['feature']}: {value['status']} ({value['current_role']})")
        for key in ("blocked_on_pending", "plan_version", "plan_stale", "batches", "ownership", "superseded", "added", "changed", "retired",
                    "skipped", "warnings", "open_questions"):
            items = value.get(key)
            for item in items if isinstance(items, list) else [items] if items else []:
                print(f"{key}: {item}")
    else:
        for key, item in value.items():
            print(f"{key}: {item}")


def main() -> int:
    args = build_parser().parse_args()
    try:
        root = find_root()
        with project_lock(root):
            output(HANDLERS[args.command](root, args), args.json)
        return 0
    except TrackerError as error:
        if args.json:
            print(json.dumps({"ok": False, "error": {"code": "tracker_error", "message": str(error)}}, separators=(",", ":")))
        else:
            print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
