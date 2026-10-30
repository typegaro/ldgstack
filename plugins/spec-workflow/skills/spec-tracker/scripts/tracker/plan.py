"""Implementation plans written by the planner: parsed from Markdown, stored in the record, sliced per batch for briefs."""
from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any

from . import paths as lanes
from .store import TrackerError

HEADING = re.compile(r"^(#{2,3})\s+(.+?)\s*$", re.M)
BATCH = re.compile(r"^batch\s+([0-9]+)\b[:.\s-]*(.*)$", re.I)
REQUIRED = {"ownership": "Ownership", "findings": "Findings", "stop": "Stop conditions", "out": "Out of scope"}
FENCE = re.compile(r"^```.*?^```", re.M | re.S)
REQ_ID = re.compile(r"\bREQ-[0-9]+\b")
REQUIRES = re.compile(r"^\s*(?:\*\*)?Requires:(?:\*\*)?\s*(.+?)\s*$", re.I | re.M)
GLOB = re.compile(r"`([^`\s]+)`")
# Spec size that requires a plan before the implementer starts, and the size that requires batched briefs.
PLAN_REQUIREMENTS, PLAN_AREAS = 3, 1
BATCH_REQUIREMENTS, BATCH_AREAS = 10, 2


def sections(text: str) -> list[tuple[str, str]]:
    """(heading, body) for every level-2 heading; level-3 headings stay inside their section except batches."""
    found: list[tuple[str, str]] = []
    fences = [match.span() for match in FENCE.finditer(text)]
    marks = [match for match in HEADING.finditer(text)
             if (match.group(1) == "##" or BATCH.match(match.group(2))) and not any(a <= match.start() < b for a, b in fences)]
    for index, match in enumerate(marks):
        end = marks[index + 1].start() if index + 1 < len(marks) else len(text)
        found.append((match.group(2).strip(), text[match.start():end].strip()))
    return found


def kind(heading: str) -> str:
    lowered = heading.lower()
    for key, title in REQUIRED.items():
        if lowered.startswith(title.lower()) or (key == "ownership" and lowered.startswith("ownership")):
            return key
    return "batch" if BATCH.match(heading) else "other"


def ownership_globs(body: str) -> list[str]:
    globs = []
    for line in body.splitlines()[1:]:
        line = line.strip()
        if not line.startswith(("-", "*")):
            continue
        for candidate in GLOB.findall(line):
            try:
                globs.append(lanes.validate(candidate))
            except ValueError as error:
                raise TrackerError(f"plan ownership: {error}") from error
    return list(dict.fromkeys(globs))


def parse_requires(body: str, number: int) -> list[str] | None:
    """Specs a batch needs accepted before it can run: `**Requires:** 0040, 0041`, `none` (independent), or None when absent."""
    match = REQUIRES.search(FENCE.sub("", body))
    if match is None:
        return None
    value = match.group(1).strip().strip("*").strip()
    if value.lower().rstrip(".") == "none":
        return []
    ids = re.findall(r"\b[0-9]{1,4}\b", value)
    if not ids:
        raise TrackerError(f"plan batch {number}: `Requires` must list spec IDs (e.g. 0040, 0041) or `none`; got {value!r}")
    return list(dict.fromkeys(f"{int(item):04d}" for item in ids))


def parse(text: str, requirement_ids: list[str]) -> tuple[dict[str, Any], list[str]]:
    """Validate a plan against the template (references/planning.md); returns the stored form and warnings."""
    parts = sections(text)
    kinds = {kind(heading) for heading, _ in parts}
    missing = [title for key, title in REQUIRED.items() if key not in kinds]
    batches = []
    for heading, body in parts:
        match = BATCH.match(heading)
        if match:
            ids = list(dict.fromkeys(REQ_ID.findall(body)))
            number = int(match.group(1))
            batches.append({"number": number, "title": match.group(2).strip(), "requirements": ids, "requires": parse_requires(body, number), "text": body})
    if not batches:
        missing.append("Batch 1 (at least one `## Batch N: <title>` section)")
    if missing:
        raise TrackerError("plan is missing sections: " + ", ".join(missing) + " (template: spec-implementer references/planning.md)")
    numbers = [item["number"] for item in batches]
    if numbers != list(range(1, len(batches) + 1)):
        raise TrackerError(f"plan batches must be numbered 1..{len(batches)} in order; found {numbers}")
    known = set(requirement_ids)
    unknown = sorted({rid for item in batches for rid in item["requirements"]} - known)
    if unknown:
        raise TrackerError(f"plan names unknown requirement IDs: {', '.join(unknown)} (see `tracker requirement list`)")
    empty = [str(item["number"]) for item in batches if not item["requirements"]]
    if empty:
        raise TrackerError(f"plan batches without requirement IDs: {', '.join(empty)}; list the REQ-n each batch implements")
    ownership = ownership_globs(next(body for heading, body in parts if kind(heading) == "ownership"))
    if not ownership:
        raise TrackerError("plan ownership lists no globs; write one `- \\`glob\\`` bullet per owned path")
    covered = {rid for item in batches for rid in item["requirements"]}
    warnings = [f"requirements in no batch: {', '.join(rid for rid in requirement_ids if rid not in covered)}"] if known - covered else []
    common = {key: next((body for heading, body in parts if kind(heading) == key), "") for key in ("ownership", "findings", "stop", "out")}
    return {"ownership": ownership, "batches": batches, "sections": common, "text": text}, warnings


def latest(record: dict[str, Any], any_generation: bool = False) -> dict[str, Any] | None:
    plans = record.get("plans") or []
    if any_generation:
        return plans[-1] if plans else None
    current = int(record.get("generation", 1))
    matching = [item for item in plans if int(item.get("generation", 1)) == current]
    return matching[-1] if matching else None


def mark_stale(plan: dict[str, Any], requirement_ids: list[str], reason: str, at: str) -> None:
    """spec-sync keeps the plan but flags the requirements it no longer matches (#62); a new `plan add` clears it."""
    stale = plan.setdefault("stale", {"requirements": [], "reasons": []})
    stale["requirements"] = list(dict.fromkeys(stale["requirements"] + requirement_ids))
    stale["reasons"].append(reason)
    stale["at"] = at


def stale_text(plan: dict[str, Any] | None) -> str:
    """'' for a current plan, else which requirements changed after planning and the batches they sit in."""
    stale = (plan or {}).get("stale")
    if not stale:
        return ""
    where = {rid: item["number"] for item in plan["batches"] for rid in item["requirements"]}
    parts = [f"{rid} (batch {where[rid]})" if rid in where else f"{rid} (no batch)" for rid in stale["requirements"]]
    return (f"plan v{plan['version']} is stale: spec-sync changed {', '.join(parts)} after planning; the spec's effective text wins "
            "for those (replan if batches no longer fit)")


def batch(plan: dict[str, Any], number: int) -> dict[str, Any]:
    for item in plan["batches"]:
        if item["number"] == number:
            return item
    raise TrackerError(f"plan v{plan['version']} has batches 1..{len(plan['batches'])}; no batch {number}")


PATH = re.compile(r"(?<![\w/.:-])((?:[\w.-]+/)+[\w.*-]*[\w*])")
FILES_SECTION = re.compile(r"\*\*Files:\*\*(.*?)(?=\n\s*(?:[-*]\s*)?\*\*[A-Z][\w ]*:\*\*|\Z)", re.S)


def batch_lane(plan: dict[str, Any], number: int) -> list[str]:
    """The paths batch `number` edits (#73): its `**Files:**` section (else the whole batch text), backticks optional,
    `:line` suffixes dropped, and only paths inside the plan's ownership. Empty when the batch names none."""
    text = batch(plan, number)["text"]
    section = FILES_SECTION.search(text)
    found = []
    for raw in PATH.findall(section.group(1) if section else text):
        candidate = re.sub(r":[0-9]+(?:-[0-9]+)?$", "", raw).rstrip("/")
        try:
            candidate = lanes.validate(candidate)
        except ValueError:
            continue
        if any(lanes.matches([owner], candidate) or lanes.covers(owner, candidate) for owner in plan["ownership"]):
            found.append(candidate)
    return list(dict.fromkeys(found))


def areas(record: dict[str, Any]) -> set[str]:
    """Top-level project areas a spec touches: the implementer lane, the plan's ownership, and changed files."""
    globs = [glob for item in record.get("assignments", []) if item["status"] == "active" and item["role"] == "implementer"
             for glob in item.get("paths") or []]
    plan = latest(record)
    globs += plan["ownership"] if plan else []
    globs += record.get("changed_files", [])
    return {PurePosixPath(glob).parts[0] for glob in globs if glob and not glob.startswith("*")}


def needs_plan(record: dict[str, Any]) -> bool:
    return len(record["requirements"]) > PLAN_REQUIREMENTS or len(areas(record)) > PLAN_AREAS


def needs_batches(record: dict[str, Any]) -> bool:
    plan = latest(record)
    return (len(record["requirements"]) > BATCH_REQUIREMENTS or len(areas(record)) > BATCH_AREAS
            or bool(plan and len(plan["batches"]) > 1))


def brief_text(plan: dict[str, Any], number: int | None, show: str) -> str:
    """The plan text an executor brief carries: one batch plus the ownership (or the whole plan)."""
    if number is None:
        return plan["text"].strip()
    chosen = batch(plan, number)
    return "\n\n".join([plan["sections"]["ownership"], chosen["text"],
                        f"(Batch {number} of {len(plan['batches'])}. Stop conditions and out of scope: `{show}`.)"])
