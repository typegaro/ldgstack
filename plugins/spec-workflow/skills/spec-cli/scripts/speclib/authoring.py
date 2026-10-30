"""Create new specs with tool-generated frontmatter."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from pathlib import Path

from . import frontmatter
from .catalog import Catalog, label
from .errors import SpecError

DRAFTS = "specs/.drafts"

SKELETON = "# {title}\n\n## Context\n\n## Requirements\n\n- **R1** \n"
TESTABILITY = "\n## Testability\n\n- **R2** [ops] Inspection: \n"
PLUGIN_JSON = Path(__file__).resolve().parents[4] / ".claude-plugin" / "plugin.json"


def plugin_version() -> str:
    """The version stamped into new specs' `workflow:` key; rules introduced in a version apply in full to specs it created."""
    try:
        value = json.loads(PLUGIN_JSON.read_text(encoding="utf-8")).get("version", "")
    except (OSError, ValueError):
        value = ""
    return value if frontmatter.VERSION.fullmatch(str(value)) else "0.7.1"


def slugify(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")


def parse_ids(value: str | None) -> list[int]:
    if not value:
        return []
    parts = [part.strip() for part in value.split(",")]
    if not all(part.isdigit() for part in parts):
        raise SpecError(f"expected comma-separated spec ids, got: {value}")
    return sorted({int(part) for part in parts})


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def read_draft(catalog: Catalog, value: str) -> tuple[Path, str]:
    """A body-only Markdown draft under specs/.drafts/, where subagents may write proposed spec text."""
    drafts = (catalog.root / DRAFTS).resolve()
    path = Path(value)
    path = (path if path.is_absolute() else catalog.root / path).resolve()
    if path.parent != drafts or path.suffix != ".md" or not path.is_file():
        raise SpecError(f"draft must be an existing .md file directly in {DRAFTS}/")
    body = path.read_text(encoding="utf-8")
    if frontmatter.has_frontmatter(body):
        raise SpecError("draft must be body only; the CLI writes the frontmatter")
    if not body.strip():
        raise SpecError("draft is empty")
    return path, body if body.endswith("\n") else body + "\n"


def create(catalog: Catalog, title: str, kind: str, slug: str | None, relations: dict[str, str | None], draft: str | None = None) -> dict[str, Any]:
    title = frontmatter.normalize_title(title)
    slug = slug or slugify(title)
    if not frontmatter.SLUG.fullmatch(slug):
        raise SpecError(f"slug must be lowercase kebab-case, got: {slug or '(empty)'}")
    if kind not in frontmatter.KINDS:
        raise SpecError(f"kind must be one of {', '.join(frontmatter.KINDS)}")
    number = catalog.next_id()
    if number > 9999:
        raise SpecError("spec ids are limited to 4 digits")
    meta: frontmatter.Meta = {"id": number, "slug": slug, "title": title, "kind": kind, "created": today(), frontmatter.OPTIONAL: plugin_version()}
    for relation in frontmatter.RELATIONS:
        targets = parse_ids(relations.get(relation))
        missing = [target for target in targets if target not in catalog.specs]
        if missing:
            raise SpecError(f"{relation} targets do not exist or are invalid: {missing}")
        meta[relation] = targets
    draft_path, body = read_draft(catalog, draft) if draft else (None, SKELETON.format(title=title) + (TESTABILITY if kind in ("feature", "change") else ""))
    path = catalog.root / "specs" / f"{label(number)}-{slug}.md"
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(frontmatter.serialize(meta) + "\n" + body)
    except FileExistsError as error:
        raise SpecError(f"spec file already exists: {path.name}") from error
    if draft_path:
        draft_path.unlink()
    return {"id": number, "name": path.name, "path": path.relative_to(catalog.root).as_posix()}


def read_body(catalog: Catalog, value: str) -> tuple[Path, str]:
    """A body-only Markdown file: a draft in specs/.drafts/ or any file outside specs/."""
    path = Path(value)
    path = (path if path.is_absolute() else catalog.root / path).resolve()
    specs, drafts = (catalog.root / "specs").resolve(), (catalog.root / DRAFTS).resolve()
    if specs in path.parents and path.parent != drafts:
        raise SpecError(f"--from must be a draft in {DRAFTS}/ or a file outside specs/")
    if path.parent == drafts:
        return read_draft(catalog, value)
    if path.suffix != ".md" or not path.is_file():
        raise SpecError("--from must be an existing .md file")
    body = path.read_text(encoding="utf-8")
    if frontmatter.has_frontmatter(body) or not body.strip():
        raise SpecError("--from must hold a non-empty body without frontmatter; the CLI keeps the frontmatter")
    return path, body if body.endswith("\n") else body + "\n"


def edit(catalog: Catalog, manifest: dict[str, Any], value: str, source: str, reason: str, decision: str | None,
         conflict: str | None, confirmed: bool, action: str = "edit") -> dict[str, Any]:
    """Replace a non-accepted (or unlocked) spec's body, logged in the archive manifest history (`spec log`)."""
    from .lock import save_manifest  # local import: lock imports tracker modules
    from tracker import store
    from tracker.model import now

    if not confirmed:
        raise SpecError(f"{action} requires --parent-confirmed (parent only; subagents write specs/.drafts/ and report)")
    if not reason.strip():
        raise SpecError("--reason must say why the spec changes")
    spec = catalog.get(value)
    if spec.status == "superseded" or (spec.status == "accepted" and not spec.unlocked):
        raise SpecError(f"accepted specs are frozen; put the change in a new spec: `spec new --title ... --kind change --amends {spec.id} --from <draft>`")
    needs_user = spec.status in ("in_progress", "accepted") or bool(conflict)
    if needs_user and not (decision and decision.strip()):
        why = "it resolves a conflict between specs" if conflict else f"the spec is {spec.status}"
        raise SpecError(f"{action} needs --user-decision because {why}; ask the user and quote the answer")
    source_path, body = read_body(catalog, source)
    meta, _ = frontmatter.parse(spec.path.read_text(encoding="utf-8"))
    previous = store.digest(spec.path)
    spec.path.write_text(frontmatter.serialize(meta) + "\n" + body, encoding="utf-8")
    if source_path.parent == (catalog.root / DRAFTS).resolve():
        source_path.unlink()
    entry: dict[str, Any] = {"action": "edit", "specification": spec.name, "at": now(), "reason": reason, "status_at_edit": spec.status,
                             "previous_sha256": previous, "spec_sha256": store.digest(spec.path), "via": action}
    if decision:
        entry["user_decision"] = decision
    if conflict:
        entry["conflict"] = conflict
    manifest["history"].append(entry)
    save_manifest(catalog.root, manifest)
    result = {"id": spec.id, "name": spec.name, "path": spec.path.relative_to(catalog.root).as_posix(), "logged": True}
    if spec.status == "in_progress":
        result["next"] = (f"tracker spec-sync {spec.feature} --reason \"{reason}\" --parent-confirmed "
                          "(re-imports and invalidates only changed requirements); "
                          "send the record back to the implementer if requirements changed")
    return result


def promote(catalog: Catalog, manifest: dict[str, Any], value: str, draft: str, confirmed: bool, reason: str | None,
            decision: str | None) -> dict[str, Any]:
    """Deprecated alias of `edit` for drafts."""
    return edit(catalog, manifest, value, draft, reason or "promote draft", decision, None, confirmed, action="promote")
