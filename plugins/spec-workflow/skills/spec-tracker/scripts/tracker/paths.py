"""Path globs for lane ownership (assignments). Shared by the tracker, the path-guard hook, and workflow-retro."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any

FORBIDDEN = ("specs", "implementation")
ASSIGNMENTS_DIR = "implementation/.assignments"


def validate(glob: str) -> str:
    value = glob.strip()
    if value.startswith(("/", "~")):
        raise ValueError(f"path glob must be project-relative: {glob!r}")
    value = value.rstrip("/")
    parts = PurePosixPath(value).parts
    if not value or ".." in parts:
        raise ValueError(f"path glob must be project-relative without '..': {glob!r}")
    if parts[0] in FORBIDDEN:
        raise ValueError(f"{parts[0]}/ is CLI-managed and cannot be assigned: {glob!r}")
    return value


@lru_cache(maxsize=256)
def pattern(glob: str) -> re.Pattern[str]:
    """`**` crosses directories, `*` and `?` stay within one; a glob without wildcards also owns everything below it."""
    out = []
    index = 0
    while index < len(glob):
        if glob.startswith("**", index):
            out.append(".*")
            index += 2
        elif glob[index] == "*":
            out.append("[^/]*")
            index += 1
        elif glob[index] == "?":
            out.append("[^/]")
            index += 1
        else:
            out.append(re.escape(glob[index]))
            index += 1
    return re.compile("".join(out) + "(?:/.*)?")


def matches(globs: list[str], relative: str) -> bool:
    return any(pattern(glob).fullmatch(relative) for glob in globs)


def static_prefix(glob: str) -> str:
    """The directory part before the first wildcard, used to detect overlapping assignments."""
    head = re.split(r"[*?\[]", glob, maxsplit=1)[0]
    return head if head == glob else head.rsplit("/", 1)[0] if "/" in head else ""


def overlap(first: list[str], second: list[str]) -> list[tuple[str, str]]:
    found = []
    for left in first:
        for right in second:
            a, b = static_prefix(left), static_prefix(right)
            if not a or not b or a == b or a.startswith(b + "/") or b.startswith(a + "/"):
                found.append((left, right))
    return found


def active_assignments(root: Path) -> list[dict[str, Any]]:
    """Active assignments across active records; unreadable records are skipped (the hook must never crash)."""
    found = []
    for path in sorted((root / "implementation" / "active").glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(record, dict):
            continue
        for item in record.get("assignments") or []:
            if isinstance(item, dict) and item.get("status") == "active":
                found.append({**item, "feature": record.get("feature", path.stem)})
    return found


def marker(root: Path, agent_id: str) -> Path:
    return root / ASSIGNMENTS_DIR / re.sub(r"[^A-Za-z0-9_.-]", "_", agent_id)
