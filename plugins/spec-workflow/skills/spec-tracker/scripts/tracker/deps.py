"""Dependency start guard: a spec starts only after every spec it depends_on or amends is accepted."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "spec-cli" / "scripts"))

from speclib import catalog, frontmatter  # noqa: E402
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


def spec_id(name: str) -> str:
    """Four-digit ID text from a spec file name or id (`0040-x.md` -> `0040`)."""
    return f"{int(name[:4]):04d}"


def unaccepted(root: Path, ids: list[str]) -> list[str]:
    """The given spec IDs (`0040`) that are not accepted yet."""
    accepted = {spec_id(name) for name in accepted_names(root) if name[:4].isdigit()}
    return [item for item in ids if spec_id(item) not in accepted]


def deferred_names(root: Path) -> set[str]:
    try:
        manifest = json.loads((root / "implementation" / "spec-archive.json").read_text(encoding="utf-8"))
        return set(catalog.deferrals({"history": manifest.get("history") or []}))
    except (OSError, ValueError, AttributeError, KeyError, TypeError):
        return set()


def early_startable(root: Path, spec: Path) -> bool:
    """Every unaccepted prerequisite is being implemented (active record) or startable now (its own prerequisites accepted)."""
    deferred = deferred_names(root)
    for name in pending(root, spec):
        target = root / "specs" / name
        if not target.is_file() or name in deferred:
            return False
        if (root / "implementation" / "active" / f"{target.stem}.json").is_file():
            continue
        try:
            meta, _ = frontmatter.parse(target.read_text(encoding="utf-8"))
        except (OSError, SpecError):
            return False
        if meta.get("kind") == "decision" or pending(root, target):
            return False
    return True


def blocked_batch(record: dict[str, Any], batch: dict[str, Any] | None, root: Path) -> list[str]:
    """Unaccepted specs an early record's batch still requires. No `Requires` line means all of `blocked_on`;
    `batch` None (a whole-plan or unplanned brief) means every batch's requirements."""
    if not record.get("early"):
        return []
    default = list(record.get("blocked_on") or [])
    if batch is None:
        required = default
    else:
        required = default if batch.get("requires") is None else batch["requires"]
    return unaccepted(root, required)


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
