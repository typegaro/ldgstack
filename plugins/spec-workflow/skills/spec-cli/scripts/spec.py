#!/usr/bin/env python3
"""Git for specs: create, inspect, validate, and lock append-only numbered specifications."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable

TRACKER_SCRIPTS = Path(__file__).resolve().parents[2] / "spec-tracker" / "scripts"
sys.path.insert(0, str(TRACKER_SCRIPTS))

from tracker.store import TrackerError, find_root, project_lock  # noqa: E402

from speclib import adopt, authoring, catalog, lock, preflight, testability, views  # noqa: E402
from speclib.errors import SpecError  # noqa: E402
from speclib.frontmatter import KINDS, RELATIONS  # noqa: E402

Result = Any


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage append-only numbered specifications")
    parser.add_argument("--json", action="store_true", help="emit one compact JSON result")
    commands = parser.add_subparsers(dest="command", required=True)

    new = commands.add_parser("new", help="create the next numbered spec")
    new.add_argument("--title", required=True)
    new.add_argument("--kind", required=True, choices=KINDS)
    new.add_argument("--slug")
    new.add_argument("--from", dest="draft", metavar="DRAFT", help="body from a specs/.drafts/ file (parent only)")
    for relation in RELATIONS:
        new.add_argument(f"--{relation.replace('_', '-')}", dest=relation, metavar="IDS", help="comma-separated lower spec ids")

    listing = commands.add_parser("list", help="list specs with derived status")
    listing.add_argument("--kind", choices=KINDS)
    listing.add_argument("--status", choices=catalog.STATUSES)
    for name in ("status", "next", "ready", "next-number", "preflight"):
        commands.add_parser(name)
    commands.add_parser("validate", help="frontmatter, links, and the Testability rule (error from 0.7.1-created specs, warning before)").add_argument(
        "--strict-testability", action="store_true", help="treat a missing `## Testability` as an error for every feature/change spec")

    show = commands.add_parser("show", help="print a spec, or its effective view with --effective")
    show.add_argument("spec")
    show.add_argument("--effective", action="store_true")
    commands.add_parser("log", help="transitive ancestors and descendants").add_argument("spec")
    commands.add_parser("graph", help="spec relation graph").add_argument("--mermaid", action="store_true")

    archive = confirmed(commands, "archive")
    archive.add_argument("spec")
    restore = confirmed(commands, "restore")
    restore.add_argument("spec")
    restore.add_argument("--reason", required=True)
    unlock = confirmed(commands, "unlock")
    unlock.add_argument("spec")
    unlock.add_argument("--reason", required=True)
    unlock.add_argument("--user-decision", required=True)
    confirmed(commands, "relock").add_argument("spec")
    defer = confirmed(commands, "defer")
    defer.add_argument("spec")
    defer.add_argument("--reason", required=True)
    confirmed(commands, "undefer").add_argument("spec")
    commands.add_parser("waves", help="startable, plannable (lookahead), topological levels, and deferred specs")
    promote = confirmed(commands, "promote")
    promote.add_argument("spec")
    promote.add_argument("--from", dest="draft", required=True, metavar="DRAFT", help="a specs/.drafts/ body file")
    promote.add_argument("--reason")
    promote.add_argument("--user-decision")
    edit = confirmed(commands, "edit")
    edit.add_argument("spec")
    edit.add_argument("--from", dest="source", required=True, metavar="FILE", help="body-only .md (draft or outside specs/)")
    edit.add_argument("--reason", required=True)
    edit.add_argument("--user-decision", help="required for in-progress or unlocked specs and conflict resolutions")
    edit.add_argument("--conflict", metavar="REFS", help="spec references whose conflict this edit resolves, e.g. 4:R7,22:R3")
    migrate = confirmed(commands, "adopt")
    migrate.add_argument("--dry-run", action="store_true")
    migrate.add_argument("--assign", action="append", default=[], metavar="STEM=KIND")
    migrate.add_argument("--baseline", action="append", default=[], metavar="STEM", help="mark a legacy spec accepted without a record")
    return parser


def confirmed(commands: Any, name: str) -> argparse.ArgumentParser:
    parser = commands.add_parser(name)
    parser.add_argument("--parent-confirmed", action="store_true")
    return parser


def load(root: Path) -> tuple[catalog.Catalog, lock.Manifest]:
    specs = catalog.scan(root)
    manifest = lock.load_manifest(root)
    catalog.derive_status(specs, manifest)
    specs.errors.extend(lock.lock_errors(specs, manifest))
    return specs, manifest


def summaries(specs: catalog.Catalog, kind: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
    return [
        spec.summary(specs.root) for spec in specs.ordered()
        if (kind is None or spec.kind == kind) and (status is None or spec.status == status)
    ]


def ready_summary(specs: catalog.Catalog) -> list[dict[str, Any]]:
    return [spec.summary(specs.root) for spec in catalog.ready_specs(specs)]


def next_summary(specs: catalog.Catalog) -> dict[str, Any] | None:
    spec = catalog.next_spec(specs)
    return spec.summary(specs.root) if spec else None


def run(args: argparse.Namespace) -> Result:
    root = find_root()
    with project_lock(root):
        return run_locked(root, args)


def run_locked(root: Path, args: argparse.Namespace) -> Result:
    if args.command == "preflight":
        return preflight.run(root)
    if args.command == "adopt":
        return adopt.adopt(root, args.assign, args.baseline, args.dry_run, args.parent_confirmed)
    specs, manifest = load(root)
    handlers: dict[str, Callable[[], Result]] = {
        "new": lambda: authoring.create(specs, args.title, args.kind, args.slug, {key: getattr(args, key) for key in RELATIONS}, args.draft),
        "list": lambda: summaries(specs, args.kind, args.status),
        "status": lambda: status(specs),
        "next": lambda: next_summary(specs),
        "ready": lambda: ready_summary(specs),
        "next-number": lambda: {"next_number": specs.next_id()},
        "validate": lambda: validate(specs, args.strict_testability),
        "show": lambda: views.effective(specs, specs.get(args.spec)) if args.effective else views.show(specs, specs.get(args.spec)),
        "log": lambda: views.log(specs, specs.get(args.spec), manifest),
        "graph": lambda: views.graph(specs),
        "archive": lambda: lock.archive(specs, manifest, args.spec, args.parent_confirmed),
        "restore": lambda: lock.restore(specs, manifest, args.spec, args.reason, args.parent_confirmed),
        "unlock": lambda: lock.unlock(specs, manifest, args.spec, args.reason, args.user_decision, args.parent_confirmed),
        "relock": lambda: lock.relock(specs, manifest, args.spec, args.parent_confirmed),
        "defer": lambda: lock.defer(specs, manifest, args.spec, args.reason, args.parent_confirmed),
        "undefer": lambda: lock.undefer(specs, manifest, args.spec, args.parent_confirmed),
        "waves": lambda: waves(specs),
        "promote": lambda: authoring.promote(specs, manifest, args.spec, args.draft, args.parent_confirmed, args.reason, args.user_decision),
        "edit": lambda: authoring.edit(specs, manifest, args.spec, args.source, args.reason, args.user_decision, args.conflict, args.parent_confirmed),
    }
    return handlers[args.command]()


def waves(specs: catalog.Catalog) -> dict[str, Any]:
    try:
        return catalog.waves(specs)
    except SpecError as error:
        raise SpecError(f"cannot schedule: {error}") from error


def waves_text(value: dict[str, Any]) -> str:
    def names(items: list[dict[str, Any]], key: str = "", label: str = "") -> str:
        def one(item: dict[str, Any]) -> str:
            waiting = f" ({label} {', '.join(catalog.label(target) for target in item[key])})" if key and item.get(key) else ""
            return f"{catalog.label(item['id'])} {item['name'][5:-3]}{waiting}"
        return ", ".join(one(item) for item in items) or "none"

    lines = [f"startable: {names(value['startable'])}", f"plannable: {names(value['plannable'], 'blocked_on', 'blocked on')}"]
    lines.extend(f"wave {index}: {names(group, 'waiting_on', 'waiting on')}" for index, group in enumerate(value["waves"]))
    deferred = ", ".join(f"{catalog.label(item['id'])} {item['name'][5:-3]} ({item['reason']})" for item in value["deferred"]) or "none"
    return "\n".join([*lines, f"deferred: {deferred}"])


def status(specs: catalog.Catalog) -> dict[str, Any]:
    try:
        ready, next_item = ready_summary(specs), next_summary(specs)
    except SpecError as error:
        ready, next_item = [], None
        specs.errors.append(str(error))
    return {"specifications": summaries(specs), "next": next_item, "ready": [item["id"] for item in ready],
            "next_number": specs.next_id(), "errors": specs.errors}


def validate(specs: catalog.Catalog, strict: bool = False) -> dict[str, Any]:
    errors, warnings = testability.findings(specs, strict)
    if specs.errors or errors:
        raise SpecError("validation failed: " + "; ".join(specs.errors + errors))
    result: dict[str, Any] = {"valid": True, "specification_count": len(specs.specs)}
    if warnings:
        result["warnings"] = warnings
    return result


def spec_line(item: dict[str, Any]) -> str:
    flag = " unlocked" if item.get("unlocked") else ""
    waiting = f" (waiting on {', '.join(catalog.label(target) for target in item['waiting_on'])})" if item.get("waiting_on") and item["status"] in ("draft", "in_progress") else ""
    return f"{catalog.label(item['id'])} {item['slug']} [{item['status']}{flag}] {item['kind']}: {item['title']}{waiting}"


def text(args: argparse.Namespace, value: Result) -> str:
    if value is None:
        return "none"
    if args.command == "show":
        return views.effective_text(value) if args.effective else value["content"].rstrip("\n")
    if args.command == "log":
        return views.log_text(value)
    if args.command == "graph":
        return views.mermaid(value) if args.mermaid else json.dumps(value, indent=2)
    if args.command == "waves":
        return waves_text(value)
    if args.command in ("list", "ready"):
        return "\n".join(spec_line(item) for item in value) or "none"
    if args.command == "next":
        return spec_line(value)
    if args.command == "status":
        lines = [spec_line(item) for item in value["specifications"]]
        lines.append(f"next: {value['next']['name'] if value['next'] else 'none'}")
        lines.append(f"ready: {', '.join(catalog.label(item) for item in value['ready']) or 'none'}")
        lines.append(f"next_number: {value['next_number']}")
        lines.extend(f"error: {error}" for error in value["errors"])
        return "\n".join(lines)
    if args.command == "validate":
        return "\n".join([f"valid: {value['valid']} ({value['specification_count']} specs)", *(f"warning: {item}" for item in value.get("warnings", []))])
    return "\n".join(f"{key}: {item}" for key, item in value.items())


def main() -> int:
    args = build_parser().parse_args()
    try:
        value = run(args)
    except (SpecError, TrackerError) as error:
        if args.json:
            print(json.dumps({"ok": False, "error": {"code": "spec_error", "message": str(error)}}, separators=(",", ":")))
        else:
            print(f"error: {error}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"ok": True, "result": value}, separators=(",", ":")))
    else:
        print(text(args, value))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
