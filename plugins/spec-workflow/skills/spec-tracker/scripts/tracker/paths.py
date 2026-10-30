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


def depth_range(glob: str) -> tuple[int, float]:
    """How many path segments a glob's matches can have: `*` stays in its segment, `**` and a literal last segment
    (a directory owns its subtree) are open-ended."""
    segments = glob.split("/")
    if "**" in glob:
        return len(static_prefix(glob).split("/")) + 1 if static_prefix(glob) else 1, float("inf")
    return len(segments), float("inf") if not re.search(r"[*?\[]", segments[-1]) else len(segments)


def overlap(first: list[str], second: list[str]) -> list[tuple[str, str]]:
    found = []
    for left in first:
        for right in second:
            wild_left, wild_right = bool(re.search(r"[*?\[]", left)), bool(re.search(r"[*?\[]", right))
            if not wild_left or not wild_right:
                # A literal path overlaps a glob only if the glob selects it, or it is a directory above the glob.
                literal, glob = (left, right) if not wild_left else (right, left)
                if pattern(glob).fullmatch(literal) or pattern(literal).fullmatch(static_prefix(glob) or glob):
                    found.append((left, right))
                continue
            a, b = static_prefix(left), static_prefix(right)
            if not (not a or not b or a == b or a.startswith(b + "/") or b.startswith(a + "/")):
                continue
            (lo1, hi1), (lo2, hi2) = depth_range(left), depth_range(right)
            if max(lo1, lo2) <= min(hi1, hi2):
                found.append((left, right))
    return found


def covers(outer: str, inner: str) -> bool:
    """Whether every path `inner` can select is selected by `outer`: equal globs, or `outer` is `dir/**` or a literal
    directory/file and `inner`'s literal part lies inside it."""
    if outer == inner:
        return True
    base = outer[:-3] if outer.endswith("/**") else outer if not re.search(r"[*?\[]", outer) else None
    head = static_prefix(inner) if re.search(r"[*?\[]", inner) else inner
    return base is not None and (head == base or head.startswith(base + "/"))


def excluded(item: dict[str, Any]) -> list[str]:
    """Globs carved out of an assignment for another lane (`assign --carve`)."""
    return [entry["glob"] for entry in item.get("carved") or []]


def owns(item: dict[str, Any], relative: str) -> bool:
    return matches(item.get("paths") or [], relative) and not matches(excluded(item), relative)


def lane_overlap(globs: list[str], item: dict[str, Any]) -> list[tuple[str, str]]:
    """Overlapping (ours, theirs) pairs against one assignment, ignoring globs carved out of it."""
    carved = excluded(item)
    return [(left, right) for left, right in overlap(globs, item.get("paths") or []) if not any(covers(glob, left) for glob in carved)]


def narrower(root: Path, glob: str, taken: list[str], limit: int = 8) -> list[str]:
    """Existing children under `glob`'s literal directory that `glob` selects and no `taken` glob overlaps: the
    narrowest lane that avoids another spec's paths (one level of recursion into partly taken directories)."""
    found: list[str] = []

    def walk(base: str, depth: int) -> None:
        directory = root / base if base else root
        try:
            children = sorted(directory.iterdir())
        except OSError:
            return
        for child in children:
            relative = f"{base}/{child.name}" if base else child.name
            if child.name.startswith(".") or not pattern(glob).fullmatch(relative) or len(found) >= limit:
                continue
            candidate = f"{relative}/**" if child.is_dir() else relative
            if not overlap([candidate], taken):
                found.append(candidate)
            elif child.is_dir() and depth < 1 and not any(covers(item, candidate) for item in taken):
                walk(relative, depth + 1)

    walk(static_prefix(glob) if re.search(r"[*?\[]", glob) else glob, 0)
    return found


def claimed(root: Path, assignment: str) -> bool:
    """Whether some agent's marker (written by the hook on `claim`) binds this assignment."""
    directory = root / ASSIGNMENTS_DIR
    for path in directory.glob("*") if directory.is_dir() else []:
        try:
            if path.read_text(encoding="utf-8").strip() == assignment:
                return True
        except OSError:
            continue
    return False


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
