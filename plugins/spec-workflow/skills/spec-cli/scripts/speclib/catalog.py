"""Discovery, validation, and derived status of numbered specs."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import frontmatter
from .errors import SpecError

FILENAME = re.compile(r"([0-9]{4})-([a-z0-9]+(?:-[a-z0-9]+)*)\.md")
TOLERATED = {"README.md"}
STATUSES = ("draft", "deferred", "in_progress", "accepted", "superseded")


@dataclass
class Spec:
    id: int
    slug: str
    title: str
    kind: str
    created: str
    relations: dict[str, list[int]]
    path: Path
    status: str = "draft"
    unlocked: bool = False
    amended_by: list[int] = field(default_factory=list)
    superseded_by: list[int] = field(default_factory=list)
    waiting_on: list[int] = field(default_factory=list)
    deferral: dict[str, Any] | None = None
    workflow: str | None = None
    body: str = ""

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def feature(self) -> str:
        return self.path.stem

    def summary(self, root: Path) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "feature": self.feature, "slug": self.slug, "title": self.title,
            "kind": self.kind, "status": self.status, "unlocked": self.unlocked, "path": self.path.relative_to(root).as_posix(),
            "created": self.created, **self.relations, "amended_by": self.amended_by, "superseded_by": self.superseded_by,
            "waiting_on": self.waiting_on, **({"workflow": self.workflow} if self.workflow else {}),
        }


@dataclass
class Catalog:
    root: Path
    specs: dict[int, Spec]
    errors: list[str]
    file_ids: set[int]

    def ordered(self) -> list[Spec]:
        return [self.specs[key] for key in sorted(self.specs)]

    def get(self, value: str) -> Spec:
        if value.isdigit():
            spec = self.specs.get(int(value))
        else:
            name = Path(value).name
            name = name if name.endswith(".md") else name + ".md"
            spec = next((item for item in self.specs.values() if item.name == name), None)
        if spec is None:
            raise SpecError(f"unknown or invalid specification: {value}")
        return spec

    def next_id(self) -> int:
        return max(self.file_ids, default=-1) + 1


def label(number: int) -> str:
    return f"{number:04d}"


def read_spec(path: Path) -> Spec:
    match = FILENAME.fullmatch(path.name)
    if not match:
        raise SpecError("file name must be NNNN-<slug>.md")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise SpecError(f"cannot read: {error}") from error
    meta, body = frontmatter.parse(text)
    if meta["id"] != int(match.group(1)):
        raise SpecError(f"frontmatter id {meta['id']} does not match file name number")
    if meta["slug"] != match.group(2):
        raise SpecError(f"frontmatter slug {meta['slug']} does not match file name slug")
    relations = {key: meta[key] for key in frontmatter.RELATIONS}
    return Spec(meta["id"], meta["slug"], meta["title"], meta["kind"], meta["created"], relations, path,
                workflow=meta.get(frontmatter.OPTIONAL), body=body)


def relation_errors(specs: dict[int, Spec]) -> list[str]:
    errors: list[str] = []
    for spec in specs.values():
        for relation, targets in spec.relations.items():
            for target in targets:
                if target >= spec.id:
                    errors.append(f"{spec.name}: {relation} {target} must link to a lower id")
                elif target not in specs:
                    errors.append(f"{spec.name}: {relation} {target} does not exist")
        both = set(spec.relations["amends"]) & set(spec.relations["supersedes"])
        if both:
            errors.append(f"{spec.name}: cannot both amend and supersede {sorted(both)}")
    return errors


def scan(root: Path) -> Catalog:
    specs: dict[int, Spec] = {}
    errors: list[str] = []
    file_ids: set[int] = set()
    directory = root / "specs"
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.suffix != ".md" or path.name in TOLERATED:
            continue
        match = FILENAME.fullmatch(path.name)
        if not match:
            errors.append(f"{path.name}: not a numbered spec (expected NNNN-<slug>.md; create specs with `spec.py new`)")
            continue
        file_ids.add(int(match.group(1)))
        try:
            spec = read_spec(path)
        except SpecError as error:
            errors.append(f"{path.name}: {error}")
            continue
        if spec.id in specs:
            errors.append(f"duplicate spec id {spec.id}: {specs[spec.id].name} and {path.name}")
            continue
        specs[spec.id] = spec
    errors.extend(relation_errors(specs))
    return Catalog(root, specs, errors, file_ids)


def deferrals(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Specs currently deferred, replayed from the manifest history (`defer` adds, `undefer` removes)."""
    found: dict[str, dict[str, Any]] = {}
    for entry in manifest["history"]:
        if entry.get("action") == "defer":
            found[entry["specification"]] = {"reason": entry.get("reason", ""), "at": entry.get("at", "")}
        elif entry.get("action") == "undefer":
            found.pop(entry["specification"], None)
    return found


def derive_status(catalog: Catalog, manifest: dict[str, Any]) -> None:
    archived = manifest["archived"]
    deferred = deferrals(manifest)
    active = catalog.root / "implementation" / "active"
    for spec in catalog.specs.values():
        entry = archived.get(spec.name)
        spec.unlocked = bool(entry and entry.get("unlocked"))
        if entry is not None:
            spec.status = "accepted"
        elif (active / f"{spec.feature}.json").is_file():
            spec.status = "in_progress"
        elif spec.name in deferred:
            spec.status, spec.deferral = "deferred", deferred[spec.name]
    accepted = [spec for spec in catalog.ordered() if spec.status == "accepted"]
    for spec in catalog.ordered():
        for target in spec.relations["amends"]:
            if target in catalog.specs:
                catalog.specs[target].amended_by.append(spec.id)
        for target in spec.relations["supersedes"]:
            if target in catalog.specs:
                catalog.specs[target].superseded_by.append(spec.id)
    for spec in accepted:
        for target in spec.relations["supersedes"]:
            if target in catalog.specs:
                catalog.specs[target].status = "superseded"
    derive_waiting(catalog)


PREREQUISITES = ("depends_on", "amends")


def prerequisites(spec: Spec) -> list[int]:
    return sorted({target for relation in PREREQUISITES for target in spec.relations[relation]})


def check_cycles(catalog: Catalog) -> None:
    """Valid specs link only to lower ids, so a cycle means validation already failed; report it clearly anyway."""
    state: dict[int, str] = {}

    def visit(node: int, path: list[int]) -> None:
        state[node] = "visiting"
        for target in prerequisites(catalog.specs[node]):
            if target not in catalog.specs:
                continue
            if state.get(target) == "visiting":
                cycle = path[path.index(target):] + [target] if target in path else [node, target]
                raise SpecError("dependency cycle: " + " -> ".join(label(item) for item in cycle))
            if target not in state:
                visit(target, path + [target])
        state[node] = "done"

    for spec in catalog.ordered():
        if spec.id not in state:
            visit(spec.id, [spec.id])


def derive_waiting(catalog: Catalog) -> None:
    """A spec waits on every depends_on/amends target that is not accepted (or superseded by an accepted spec)."""
    for spec in catalog.specs.values():
        spec.waiting_on = [
            target for target in prerequisites(spec)
            if target not in catalog.specs or catalog.specs[target].status not in ("accepted", "superseded")
        ]


def ready_specs(catalog: Catalog) -> list[Spec]:
    """Implementable specs whose prerequisites are all accepted, in id order."""
    check_cycles(catalog)
    return [
        spec for spec in catalog.ordered()
        if spec.kind != "decision" and spec.status in ("draft", "in_progress") and not spec.waiting_on
    ]


def next_spec(catalog: Catalog) -> Spec | None:
    ready = ready_specs(catalog)
    return ready[0] if ready else None


def startable_ids(catalog: Catalog) -> set[int]:
    return {spec.id for spec in ready_specs(catalog)}


def plannable_specs(catalog: Catalog) -> list[Spec]:
    """Draft specs whose unaccepted prerequisites are all being implemented or startable now (lookahead planning)."""
    startable = startable_ids(catalog)
    return [
        spec for spec in catalog.ordered()
        if spec.kind != "decision" and spec.status == "draft" and spec.waiting_on
        and all(target in catalog.specs and (catalog.specs[target].status == "in_progress" or target in startable)
                for target in spec.waiting_on)
    ]


def levels(catalog: Catalog) -> list[list[Spec]]:
    """Topological levels of every remaining spec (not accepted, superseded, deferred, or a decision).
    Deferred and decision prerequisites still count as unfinished, so their dependents sit one level later."""
    check_cycles(catalog)
    depth: dict[int, int] = {}

    def level(spec: Spec) -> int:
        if spec.id not in depth:
            open_targets = [target for target in spec.waiting_on if target in catalog.specs]
            depth[spec.id] = 1 + max((level(catalog.specs[target]) for target in open_targets), default=-1)
        return depth[spec.id]

    remaining = [spec for spec in catalog.ordered() if spec.kind != "decision" and spec.status in ("draft", "in_progress")]
    grouped: dict[int, list[Spec]] = {}
    for spec in remaining:
        grouped.setdefault(level(spec), []).append(spec)
    return [grouped[key] for key in sorted(grouped)]


def waves(catalog: Catalog) -> dict[str, Any]:
    """Scheduling view: what can start now, what can be planned ahead, the remaining levels, and what is deferred."""
    def brief(spec: Spec) -> dict[str, Any]:
        return {"id": spec.id, "name": spec.name, "status": spec.status, "kind": spec.kind}

    return {
        "startable": [brief(spec) for spec in ready_specs(catalog)],
        "plannable": [{**brief(spec), "blocked_on": spec.waiting_on} for spec in plannable_specs(catalog)],
        "waves": [[{**brief(spec), "waiting_on": spec.waiting_on} for spec in group] for group in levels(catalog)],
        "deferred": [{**brief(spec), "reason": (spec.deferral or {}).get("reason", ""), "at": (spec.deferral or {}).get("at", "")}
                     for spec in catalog.ordered() if spec.status == "deferred"],
    }
