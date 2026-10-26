"""Dependency start guard: a spec starts only after every spec it depends_on or amends is accepted."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "spec-cli" / "scripts"))

from speclib import frontmatter  # noqa: E402
from speclib.errors import SpecError  # noqa: E402

PREREQUISITES = ("depends_on", "amends")


def prerequisites(spec: Path) -> list[int]:
    """Ids the spec depends on or amends; a spec without parsable frontmatter (legacy) has none."""
    try:
        meta, _ = frontmatter.parse(spec.read_text(encoding="utf-8"))
    except (OSError, SpecError):
        return []
    return sorted({target for key in PREREQUISITES for target in meta.get(key) or []})


def accepted_names(root: Path) -> set[str]:
    try:
        manifest = json.loads((root / "implementation" / "spec-archive.json").read_text(encoding="utf-8"))
        return set(manifest.get("archived") or {})
    except (OSError, ValueError, AttributeError):
        return set()


def pending(root: Path, spec: Path) -> list[str]:
    """Prerequisite spec names (or ids, if missing) that are not accepted yet."""
    accepted = accepted_names(root)
    found = []
    for target in prerequisites(spec):
        names = sorted(path.name for path in (root / "specs").glob(f"{target:04d}-*.md"))
        name = names[0] if names else f"{target:04d}"
        if name not in accepted:
            found.append(name)
    return found


def guard(root: Path, record: dict[str, Any], spec: Path, confirmed: bool, decision: str | None, during: str, timestamp: str) -> None:
    """Refuse to start the spec early unless the parent records the user's decision; covered overrides are reused."""
    waiting = pending(root, spec)
    if not waiting:
        return
    overrides = record.setdefault("dependency_overrides", [])
    if any(set(waiting) <= set(item.get("pending", [])) for item in overrides):
        return
    if not (confirmed and decision and decision.strip()):
        raise ValueError(
            f"{spec.name} depends on or amends specs that are not accepted: {', '.join(waiting)}. Finish them first "
            f"(`spec ready` lists startable specs), or, only if the user decided to start early, add "
            f"--parent-confirmed --user-decision \"<the user's words>\""
        )
    overrides.append({"pending": waiting, "user_decision": decision, "during": during, "at": timestamp})
