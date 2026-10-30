"""Workflow rules: roles, handoffs, bug lifecycle, and gates."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import deps
from .store import TrackerError, digest

ROLES = ("parent", "planner", "implementer", "reviewer", "tester", "fixer", "toolsmith")
HANDOFFS = {
    "parent": {"planner", "implementer", "reviewer", "tester", "fixer", "toolsmith"},
    # The planner writes a plan (`plan add`) and returns it to the parent; it never edits code.
    "planner": {"parent"},
    # implementer -> tester only after a passed review, for requirements added since it (see review_skip_errors).
    "implementer": {"reviewer", "tester", "parent"},
    "reviewer": {"tester", "parent"},
    "tester": {"parent"},
    "fixer": {"reviewer", "parent"},
    # The toolsmith builds toolkit tools for recorded tool gaps, then the tester resumes.
    "toolsmith": {"tester", "parent"},
}
SEVERITIES = ("critical", "high", "medium", "low")
CHECK_RESULTS = ("passed", "failed", "not_run", "not_applicable")
BUG_STATUSES = ("open", "assigned", "fixed", "verified", "closed_not_a_bug", "follow_up")
# A follow-up bug is real but deferred out of the acceptance gate (low severity, or medium with a user decision).
TERMINAL_BUG_STATUSES = {"verified", "closed_not_a_bug", "follow_up"}
BUG_TRANSITIONS = {
    # action: (role allowed, statuses the bug may be in)
    "assign": ("parent", {"open"}),
    "fixed": ("fixer", {"assigned"}),
    "verify": ("tester", {"fixed"}),
    "reopen": ("tester", {"fixed", "verified"}),
    "close": ("parent", {"open", "assigned", "fixed"}),
    "follow-up": ("parent", {"open", "assigned"}),
}
# high: security, data, migration, or concurrency; every review round is a fresh reviewer.
RISK_TIERS = ("normal", "high")


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def touch(record: dict[str, Any]) -> None:
    record["updated_at"] = now()


def generation(record: dict[str, Any]) -> int:
    """Current implementation generation; legacy records are generation 1."""
    return int(record.get("generation", 1))


def in_current_generation(record: dict[str, Any], item: dict[str, Any]) -> bool:
    return int(item.get("generation", 1)) == generation(record)


def invalidate_item(item: dict[str, Any], reason: str, invalidate_implementation: bool, next_generation: int | None = None) -> None:
    """Clear a requirement's test (and optionally implementation) marks, keeping the old evidence in its history."""
    if item.get("implemented") or item.get("tested") or item.get("parent_attested"):
        item.setdefault("evidence_history", []).append({
            "generation": int(item.get("implemented_generation", item.get("tested_generation", 1))),
            "implementation": item.get("implementation", ""),
            "implementation_evidence": item.get("implementation_evidence", ""),
            "test_evidence": item.get("test_evidence", ""),
            "reason": reason,
            "invalidated_at": now(),
        })
    item.update(tested=False, test_evidence="")
    if invalidate_implementation:
        item.update(implemented=False, implementation_evidence="")
        item.pop("implemented_generation", None)
    elif item.get("implemented") and next_generation is not None:
        item["implemented_generation"] = next_generation
    item.pop("tested_generation", None)
    item.pop("parent_attested", None)


def invalidate_requirement_evidence(record: dict[str, Any], reason: str, invalidate_implementation: bool) -> None:
    for item in record.get("requirements", []):
        invalidate_item(item, reason, invalidate_implementation, generation(record) + 1)


def bump_generation(record: dict[str, Any], reason: str, invalidate_implementation: bool = False) -> int:
    previous = generation(record)
    invalidate_requirement_evidence(record, reason, invalidate_implementation)
    record["generation"] = previous + 1
    record.setdefault("generation_history", []).append({"from": previous, "to": previous + 1, "reason": reason, "at": now()})
    return previous + 1


def generation_has_work(record: dict[str, Any]) -> bool:
    current = generation(record)
    return any(item.get("implemented") and int(item.get("implemented_generation", 1)) == current for item in record.get("requirements", [])) \
        or any(in_current_generation(record, item) for item in record.get("checks", []))


def next_id(items: list[dict[str, Any]], prefix: str, legacy_prefix: str | None = None) -> str:
    """Next sequential ID; numbers under legacy_prefix (short blocker IDs) are counted too, so IDs never collide."""
    numbers = []
    for item in items:
        identifier = str(item.get("id", ""))
        for known in filter(None, (prefix, legacy_prefix)):
            suffix = identifier.removeprefix(known)
            if identifier.startswith(known) and suffix.isdigit():
                numbers.append(int(suffix))
    return f"{prefix}{max(numbers, default=0) + 1:03d}"


QUALIFIED = {"bugs": "BUG", "blockers": "BLOCKER", "tool_gaps": "GAP"}


def id_aliases(record: dict[str, Any], collection: str, identifier: str) -> set[str]:
    """Bug and blocker IDs are accepted fully qualified (BUG-<feature>-001) or short (BUG-001)."""
    kind = QUALIFIED.get(collection)
    if kind is None:
        return {identifier}
    short, qualified = f"{kind}-", f"{kind}-{record['feature']}-"
    if identifier.startswith(qualified):
        return {identifier, short + identifier.removeprefix(qualified)}
    if identifier.startswith(short):
        return {identifier, qualified + identifier.removeprefix(short)}
    return {identifier}


def find_item(record: dict[str, Any], collection: str, identifier: str) -> dict[str, Any]:
    aliases = id_aliases(record, collection, identifier)
    for item in record.get(collection, []):
        if item["id"] in aliases:
            return item
    raise TrackerError(f"unknown {collection.rstrip('s')} ID: {identifier}")


def require_role(record: dict[str, Any], allowed: set[str]) -> None:
    # A side role (a toolsmith working alongside the fixer, `assign --alongside`) may run its own role's commands.
    if record["current_role"] not in allowed and record.get("side_role") not in allowed:
        target = sorted(allowed)[0]
        raise TrackerError(
            f"operation requires role {', '.join(sorted(allowed))}; current role is {record['current_role']}. "
            f"Fix: the current role hands off (`tracker handoff {record['feature']} --to parent ...`), then the parent runs "
            f"`tracker handoff {record['feature']} --to {target} ...`"
        )


def require_confirmation(confirmed: bool, operation: str) -> None:
    if not confirmed:
        raise TrackerError(f"{operation} requires --parent-confirmed (parent only; a subagent reports to the parent instead)")


def spec_matches(root: Path, record: dict[str, Any]) -> bool:
    return digest(root / record["specification"]["path"]) == record["specification"]["sha256"]


def open_blockers(record: dict[str, Any]) -> list[dict[str, Any]]:
    # Records written before blocker history existed dropped resolved blockers, so a missing status means open.
    return [item for item in record["blockers"] if item.get("status", "open") == "open"]


def open_tool_gaps(record: dict[str, Any]) -> list[dict[str, Any]]:
    # Records written before tool gaps existed have none.
    return [item for item in record.get("tool_gaps", []) if item["status"] == "open"]


def latest_checks(record: dict[str, Any]) -> list[dict[str, Any]]:
    return list({item["name"]: item for item in record["checks"] if in_current_generation(record, item)}.values())


def gate_errors(root: Path, record: dict[str, Any], gate: str, exempt_roles: tuple[str, ...] = ("tester",)) -> list[str]:
    errors: list[str] = []
    feature = record["feature"]
    if not spec_matches(root, record):
        errors.append(f"specification hash changed (fix: `tracker spec-sync {feature} --reason \"...\" --parent-confirmed`)")
    if record.get("import_pending"):
        errors.append(f"requirements not re-imported after spec-sync (fix: `tracker requirement import {feature} --parent-confirmed`)")
    if open_blockers(record):
        errors.append(f"specification blockers remain: {', '.join(item['id'] for item in open_blockers(record))}")

    requirements = record["requirements"]
    if not requirements:
        errors.append(f"no requirements are tracked (fix: `tracker requirement import {feature}`)")
    elif any(not item["implemented"] for item in requirements):
        errors.append(f"requirements not implemented: {', '.join(item['id'] for item in requirements if not item['implemented'])}")

    checks = latest_checks(record)
    if not any(item["result"] == "passed" for item in checks):
        errors.append("no verification check has passed")
    # A tester's failed check is re-run by the tester on retest; it blocks acceptance, not the handoff back.
    failed = [item["name"] for item in checks if item["result"] == "failed"
              and (gate == "acceptance" or item.get("role") not in exempt_roles)]
    if failed:
        detail = blocking_checks(record, {"failed"}) if gate == "acceptance" else ", ".join(failed)
        errors.append(f"failing checks: {detail}")
    if gate == "acceptance":
        waiting = deps.unaccepted(root, record.get("blocked_on") or []) if record.get("early") else []
        if waiting:
            errors.append(f"early start: required specs are not accepted yet: {', '.join(waiting)}; accept them first")
        # not_run blocks only acceptance: review and (re)test handoffs don't depend on it.
        if any(item["result"] == "not_run" for item in checks):
            # Reviewer and tester checks are re-recorded by that role, never attested by the parent.
            errors.append(f"checks not run: {blocking_checks(record, {'not_run'})} (or, only with the user's decision: "
                          f"`tracker check waive {feature} <check> --reason \"...\" --user-decision \"...\" --parent-confirmed`)")
        if any(not item["tested"] for item in requirements):
            errors.append(f"requirements not independently tested: {', '.join(item['id'] for item in requirements if not item['tested'])}")
        for role, label in (("reviewer", "code review by the reviewer"), ("tester", "check executed by the independent tester")):
            if not any(item["result"] == "passed" and item.get("role") == role for item in checks):
                errors.append(f"no passing {label}")
        reviews = [item["at"] for item in checks if item["result"] == "passed" and item.get("role") == "reviewer"]
        tests = [item["at"] for item in checks if item["result"] == "passed" and item.get("role") == "tester"]
        if reviews and tests and max(tests) <= max(reviews):
            errors.append("independent tester check must be recorded after the latest passing reviewer check")
        if any(item["status"] not in TERMINAL_BUG_STATUSES for item in record["bugs"]):
            errors.append("bugs remain unverified")
        gaps = [item["id"] for item in open_tool_gaps(record)]
        if gaps:
            errors.append(f"open tool gaps: {', '.join(gaps)} (the toolsmith resolves them, or the parent defers them with a user decision)")
    return errors


def not_run_checks(record: dict[str, Any]) -> list[str]:
    return [item["name"] for item in latest_checks(record) if item["result"] == "not_run"]


def parent_attested(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Requirements the parent marked from existing check evidence (the light path); gates report them."""
    return [
        {"id": item["id"], "spec_ref": item["spec_ref"], **item["parent_attested"]}
        for item in record["requirements"] if item.get("parent_attested")
    ]


def review_skip_errors(record: dict[str, Any]) -> list[str]:
    """Why implementer -> tester may not skip review. Allowed only after a passed review, when every requirement
    implemented since that review was also added since it (parent-added amendments), and no bug is unresolved."""
    reviews = [item["at"] for item in latest_checks(record) if item.get("role") == "reviewer" and item["result"] == "passed"]
    if not reviews:
        return ["the first round must go through the reviewer"]
    last_review = max(reviews)
    errors = []
    reworked = [
        item["id"] for item in record["requirements"]
        if item.get("implemented_at", "") > last_review and item.get("added_at", "") <= last_review
    ]
    if reworked:
        errors.append(f"requirements reviewed earlier were re-implemented: {', '.join(reworked)}")
    if any(item["status"] in {"open", "assigned", "fixed"} for item in record["bugs"]):
        errors.append("bugs are not resolved")
    return errors


def open_questions(record: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in record.get("questions", []) if item["status"] == "open"]


def check_owner(record: dict[str, Any], check: dict[str, Any]) -> tuple[str, str]:
    """Who must re-record a blocking check, and the parent's handoff command that routes the record there."""
    role = check.get("role", "")
    target = role if role in {"reviewer", "tester"} else "fixer"
    note = f're-record check {check["name"]} (same name supersedes it)'
    return target, f'tracker handoff {record["feature"]} --to {target} --completed "..." --remaining "{note}"'


def blocking_checks(record: dict[str, Any], results: set[str]) -> str:
    parts = []
    for item in latest_checks(record):
        if item["result"] in results:
            target, command = check_owner(record, item)
            parts.append(f"{item['name']} ({item['result']}, recorded by {item.get('role', '?')}; the {target} re-records it: `{command}`)")
    return "; ".join(parts)


def parent_status(root: Path, record: dict[str, Any]) -> str:
    if open_blockers(record):
        return "blocked"
    if open_questions(record):
        return "needs_answer"
    if open_tool_gaps(record):
        return "needs_tooling"
    if not gate_errors(root, record, "acceptance"):
        return "ready_for_acceptance"
    if any(item["status"] not in TERMINAL_BUG_STATUSES for item in record["bugs"]):
        return "bugs_found"
    if record.get("plans") and any(not item["implemented"] for item in record["requirements"]):
        return "plan_ready"
    return "awaiting_parent"
