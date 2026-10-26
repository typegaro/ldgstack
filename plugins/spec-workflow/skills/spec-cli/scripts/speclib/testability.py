"""The `## Testability` section rule: feature/change specs carry their own inspection, drivers, faults, environment, and verification plan."""
from __future__ import annotations

import re

from . import frontmatter
from .catalog import Catalog, Spec

KINDS = ("feature", "change")
REQUIRED_FROM = (0, 7, 1)
HEADING = re.compile(r"^##\s+Testability\s*$")
NEXT_HEADING = re.compile(r"^#{1,2}\s")
FENCE = re.compile(r"^\s*(```|~~~)")
BULLET = re.compile(r"^\s*[-*] \*\*R[0-9]+[a-z]?\*\*")
EXEMPT = re.compile(r"^\s*not applicable:\s*\S", re.IGNORECASE)
HINT = ("add `## Testability` with `- **R<n>** [ops]` Inspection, Drivers, Fault and mocks, Environment, and Verification "
        "requirements (template: write-specs/references/testability.md), or `Not applicable: <reason>` for a spec with no state, UI flow, or integration")


def section(body: str) -> list[str] | None:
    """Lines of the `## Testability` section outside code fences, or None when there is none."""
    lines: list[str] | None = None
    fenced = False
    for line in body.split("\n"):
        if FENCE.match(line):
            fenced = not fenced
        if fenced:
            if lines is not None:
                lines.append(line)
            continue
        if HEADING.match(line):
            lines = []
            continue
        if lines is not None:
            if NEXT_HEADING.match(line):
                break
            lines.append(line)
    return lines


def problem(spec: Spec) -> str | None:
    if spec.kind not in KINDS:
        return None
    lines = section(spec.body)
    if lines is None:
        return f"{spec.name}: {spec.kind} spec has no `## Testability` section"
    if not any(BULLET.match(line) or EXEMPT.match(line) for line in lines):
        return f"{spec.name}: `## Testability` has no `- **R<n>**` bullets or `Not applicable: <reason>` line"
    return None


def enforced(spec: Spec, strict: bool) -> bool:
    return strict or frontmatter.version_tuple(spec.workflow) >= REQUIRED_FROM


def findings(catalog: Catalog, strict: bool = False) -> tuple[list[str], list[str]]:
    """(errors, warnings): an error for specs created by plugin 0.7.1+ (or with --strict-testability), a warning otherwise."""
    errors: list[str] = []
    warnings: list[str] = []
    frozen: list[str] = []
    for spec in catalog.ordered():
        if spec.status == "superseded":
            continue
        found = problem(spec)
        if not found:
            continue
        if enforced(spec, strict):
            errors.append(found)
        elif spec.status == "accepted":
            frozen.append(spec.name[:4])
        else:
            warnings.append(found)
    if frozen:
        warnings.append(f"{len(frozen)} accepted legacy feature/change specs have no `## Testability` ({', '.join(frozen)}); "
                        "frozen, so add testability requirements in the next spec that amends them")
    if errors:
        errors.append(HINT)
    elif warnings:
        warnings.append(HINT)
    return errors, warnings
