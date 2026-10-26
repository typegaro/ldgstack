"""One-time migration of a legacy specs/ directory to numbered specs with frontmatter."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tracker import store
from tracker.model import now

from . import frontmatter
from .catalog import TOLERATED, label
from .errors import SpecError
from .lock import load_manifest, manifest_path, save_manifest

LEGACY = re.compile(r"(0|[1-9][0-9]*)-([a-z0-9]+(?:-[a-z0-9]+)*)\.md")
FENCE = re.compile(r" {0,3}(`{3,}|~{3,})")
NUMBERED_BULLET = re.compile(r"- \*\*R([0-9]+)\*\*")
HEADING = re.compile(r"# (.+)")


@dataclass
class Item:
    old: Path
    id: int
    slug: str
    kind: str

    @property
    def new_name(self) -> str:
        return f"{label(self.id)}-{self.slug}.md"


def parse_assignments(values: list[str]) -> dict[str, str]:
    assignments: dict[str, str] = {}
    for value in values:
        stem, separator, kind = value.partition("=")
        if not separator or not stem or kind not in frontmatter.KINDS:
            raise SpecError(f"--assign must be <stem>=<kind> with kind in {', '.join(frontmatter.KINDS)}: {value}")
        if stem.endswith(".md"):
            stem = stem[:-3]
        if stem in assignments:
            raise SpecError(f"stem assigned twice: {stem}")
        assignments[stem] = kind
    return assignments


def legacy_files(root: Path) -> list[Path]:
    files = [path for path in sorted((root / "specs").iterdir()) if path.is_file() and path.suffix == ".md" and path.name not in TOLERATED]
    adopted = [path.name for path in files if frontmatter.has_frontmatter(path.read_text(encoding="utf-8"))]
    if adopted:
        raise SpecError(f"refusing to adopt: files already have frontmatter: {', '.join(adopted)}")
    if not files:
        raise SpecError("nothing to adopt: specs/ has no legacy markdown files")
    return files


def plan_items(root: Path, assignments: dict[str, str]) -> list[Item]:
    files = legacy_files(root)
    stems = {path.stem for path in files}
    unknown = sorted(set(assignments) - stems)
    if unknown:
        raise SpecError(f"--assign names unknown spec files: {', '.join(unknown)}")
    items: list[Item] = []
    unnumbered: dict[str, Path] = {}
    for path in files:
        match = LEGACY.fullmatch(path.name)
        if match:
            items.append(Item(path, int(match.group(1)), match.group(2), assignments.get(path.stem, "feature")))
        else:
            unnumbered[path.stem] = path
    numbers = [item.id for item in items]
    if len(numbers) != len(set(numbers)):
        raise SpecError("duplicate legacy spec numbers")
    missing = sorted(set(unnumbered) - set(assignments))
    if missing:
        raise SpecError(f"every unnumbered spec needs --assign <stem>=<kind>: {', '.join(missing)}")
    next_id = max(numbers, default=-1) + 1
    for stem in assignments:
        if stem not in unnumbered:
            continue
        if not frontmatter.SLUG.fullmatch(stem):
            raise SpecError(f"unnumbered spec name is not a kebab-case slug: {stem}")
        items.append(Item(unnumbered[stem], next_id, stem, assignments[stem]))
        next_id += 1
    if next_id > 10000:
        raise SpecError("spec ids are limited to 4 digits")
    return sorted(items, key=lambda item: item.id)


def rewrite_links(text: str, names: dict[str, Item]) -> tuple[str, set[int]]:
    pattern = re.compile(
        r"(?<![A-Za-z0-9_.-])(" + "|".join(re.escape(name) for name in sorted(names, key=len, reverse=True)) + r")(?![A-Za-z0-9_-])"
    )
    linked: set[int] = set()

    def replace(match: re.Match[str]) -> str:
        item = names[match.group(1)]
        linked.add(item.id)
        return item.new_name

    return pattern.sub(replace, text), linked


def outside_fences(lines: list[str]) -> list[bool]:
    """For each line, whether it lies outside a fenced code block (fence lines count as inside)."""
    flags, fence = [], ""
    for line in lines:
        match = FENCE.match(line)
        if fence:
            flags.append(False)
            if match and match.group(1)[0] == fence[0] and len(match.group(1)) >= len(fence):
                fence = ""
        elif match:
            flags.append(False)
            fence = match.group(1)
        else:
            flags.append(True)
    return flags


def number_bullets(text: str) -> str:
    lines = text.split("\n")
    outside = outside_fences(lines)
    used = [int(match.group(1)) for line, flag in zip(lines, outside) if flag and (match := NUMBERED_BULLET.match(line))]
    counter = max(used, default=0)
    for index, line in enumerate(lines):
        if outside[index] and line.startswith("- ") and not NUMBERED_BULLET.match(line):
            counter += 1
            lines[index] = f"- **R{counter}** {line[2:]}"
    return "\n".join(lines)


def title_of(text: str, slug: str) -> str:
    lines = text.split("\n")
    for line, flag in zip(lines, outside_fences(lines)):
        match = HEADING.fullmatch(line.rstrip())
        if flag and match and match.group(1).strip():
            return frontmatter.normalize_title(match.group(1))
    return slug.replace("-", " ").capitalize()


def render(item: Item, names: dict[str, Item]) -> str:
    text = item.old.read_text(encoding="utf-8")
    text, linked = rewrite_links(text, names)
    created = datetime.fromtimestamp(item.old.stat().st_mtime, timezone.utc).date().isoformat()
    meta: frontmatter.Meta = {
        "id": item.id, "slug": item.slug, "title": title_of(text, item.slug), "kind": item.kind, "created": created,
        "depends_on": [], "amends": [], "supersedes": [], "references": sorted(target for target in linked if target < item.id),
    }
    return frontmatter.serialize(meta) + "\n" + number_bullets(text)


def check_state(root: Path, names: dict[str, Item]) -> dict[str, Any]:
    manifest = load_manifest(root)
    for name, entry in manifest["archived"].items():
        if name not in names:
            raise SpecError(f"archived specification is not a legacy spec file: {name}")
        if entry.get("spec_sha256") != store.digest(names[name].old):
            raise SpecError(f"archived specification hash changed; resolve before adopting: {name}")
        record = f"implementation/archive/{Path(name).stem}.json"
        if entry.get("implementation_record") != record or not (root / record).is_file():
            raise SpecError(f"archived implementation record is missing or misplaced: {name}")
    for item in names.values():
        if (root / "specs" / item.new_name).exists():
            raise SpecError(f"target file already exists: specs/{item.new_name}")
    return manifest


def migrate_records(root: Path, item: Item, old_hash: str, new_hash: str) -> list[str]:
    old, new = item.old.stem, Path(item.new_name).stem
    migrated = []
    for archived in (False, True):
        if not store.record_path(root, old, archived).is_file():
            continue
        if store.record_path(root, new, archived).exists():
            raise SpecError(f"implementation record already exists for {new}")
        record = store.load(root, old, archived)
        specification = record["specification"]
        record["feature"] = new
        specification["path"] = f"specs/{item.new_name}"
        if specification["sha256"] == old_hash:
            specification.setdefault("history", []).append(
                {"previous_sha256": old_hash, "sha256": new_hash, "reason": "adopt", "at": now()}
            )
            specification["sha256"] = new_hash
        store.save(root, record, archived)
        store.remove(root, old, archived)
        migrated.append(f"{'archive' if archived else 'active'}/{old} -> {new}")
    return migrated


def baseline_items(root: Path, names: dict[str, Item], manifest: dict[str, Any], stems: list[str]) -> list[Item]:
    by_stem = {item.old.stem: item for item in names.values()}
    items = []
    for stem in dict.fromkeys(stem.removesuffix(".md") for stem in stems):
        item = by_stem.get(stem)
        if item is None:
            raise SpecError(f"--baseline names an unknown spec file: {stem}")
        if item.old.name in manifest["archived"]:
            raise SpecError(f"--baseline spec is already archived: {stem}")
        if any(store.record_path(root, stem, archived).is_file() for archived in (False, True)):
            raise SpecError(f"--baseline spec has an implementation record: {stem}")
        items.append(item)
    return items


def baseline_entry(root: Path, item: Item, timestamp: str) -> dict[str, Any]:
    return {
        "spec_sha256": store.digest(root / "specs" / item.new_name), "implementation_record": None,
        "implementation_sha256": None, "archived_at": timestamp, "baseline": True,
    }


def adopt(root: Path, assign: list[str], baseline: list[str], dry_run: bool, confirmed: bool) -> dict[str, Any]:
    if not confirmed:
        raise SpecError("adopt requires --parent-confirmed")
    items = plan_items(root, parse_assignments(assign))
    names = {item.old.name: item for item in items}
    manifest = check_state(root, names)
    baselines = baseline_items(root, names, manifest, baseline)
    mapping = {item.old.name: item.new_name for item in items}
    result: dict[str, Any] = {
        "dry_run": dry_run, "mapping": mapping, "kinds": {item.new_name: item.kind for item in items},
        "baseline": [item.new_name for item in baselines],
    }
    if dry_run:
        return result
    contents = {item.old.name: render(item, names) for item in items}
    old_hashes = {item.old.name: store.digest(item.old) for item in items}
    records: list[str] = []
    for item in items:
        target = root / "specs" / item.new_name
        with target.open("x", encoding="utf-8") as handle:
            handle.write(contents[item.old.name])
        item.old.unlink()
        records.extend(migrate_records(root, item, old_hashes[item.old.name], store.digest(target)))
    archived = {}
    for name, entry in manifest["archived"].items():
        item = names[name]
        entry = {**entry, "spec_sha256": store.digest(root / "specs" / item.new_name)}
        record = f"implementation/archive/{Path(item.new_name).stem}.json"
        entry.update(implementation_record=record, implementation_sha256=store.digest(root / record))
        archived[item.new_name] = entry
    timestamp = now()
    history: list[dict[str, Any]] = [{"action": "adopt", "mapping": mapping, "at": timestamp}]
    for item in baselines:
        archived[item.new_name] = baseline_entry(root, item, timestamp)
        history.append({"action": "baseline", "specification": item.new_name, "at": timestamp, **archived[item.new_name]})
    if manifest_path(root).exists() or archived:
        manifest["archived"] = dict(sorted(archived.items()))
        manifest["history"].extend(history)
        save_manifest(root, manifest)
    return {**result, "records": records, "archived": sorted(archived)}
