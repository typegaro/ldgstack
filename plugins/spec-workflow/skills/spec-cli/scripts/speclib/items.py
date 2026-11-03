"""Backlog items inside spec bodies: `- **L<n>**` (defined later) and `- **A<n>**` (accepted risk), and the newer specs that
resolve them with a `Resolves <id>:L<n>` line. Status is derived: an item is resolved once any spec resolves it."""
from __future__ import annotations

import re
from typing import Any

from .catalog import Catalog, Spec, label

ITEM = re.compile(r"^\s*[-*] \*\*([LA])([0-9]+)\*\*\s*(.*)$")
FENCE = re.compile(r"^\s*(```|~~~)")
RESOLVES = re.compile(r"\bResolves\b(.*)$")
REFERENCE = re.compile(r"\b([0-9]+):([LA])([0-9]+)\b")
TYPES = {"L": "later", "A": "risk"}
PREFIXES = {value: key for key, value in TYPES.items()}


def lines(spec: Spec) -> list[tuple[int, str]]:
    """Body lines outside code fences, with their 1-based line number in the file."""
    offset = spec.path.read_text(encoding="utf-8").count("\n") - spec.body.count("\n")
    found, fenced = [], False
    for number, line in enumerate(spec.body.split("\n"), start=offset + 1):
        if FENCE.match(line):
            fenced = not fenced
        elif not fenced:
            found.append((number, line))
    return found


def declared(spec: Spec) -> list[dict[str, Any]]:
    items = []
    for number, line in lines(spec):
        match = ITEM.match(line)
        if match:
            text = match.group(3).strip()
            title, _, detail = text.partition(":")
            items.append({"id": match.group(1) + match.group(2), "type": TYPES[match.group(1)], "title": title.strip(),
                          "detail": detail.strip(), "line": number})
    return items


def resolves(spec: Spec) -> list[tuple[int, str]]:
    """`(spec id, item id)` pairs this spec resolves, from every `Resolves ...` line."""
    found: list[tuple[int, str]] = []
    for _, line in lines(spec):
        match = RESOLVES.search(line)
        if match:
            found.extend((int(target), prefix + number) for target, prefix, number in REFERENCE.findall(match.group(1)))
    return found


def collect(catalog: Catalog) -> tuple[list[dict[str, Any]], list[str]]:
    """Every item with its resolvers, and the validation errors (duplicate ids, dangling or forward `Resolves`)."""
    items: dict[tuple[int, str], dict[str, Any]] = {}
    errors: list[str] = []
    for spec in catalog.ordered():
        for item in declared(spec):
            key = (spec.id, item["id"])
            if key in items:
                errors.append(f"{spec.name}: duplicate item {item['id']}")
                continue
            items[key] = {"ref": f"{spec.id}:{item['id']}", "spec": spec.id, "spec_name": spec.name, "spec_title": spec.title,
                          "spec_status": spec.status, **item, "resolved_by": []}
    for spec in catalog.ordered():
        for target, item_id in resolves(spec):
            reference = f"{target}:{item_id}"
            if target >= spec.id:
                errors.append(f"{spec.name}: Resolves {reference} must point to a lower spec id")
            elif (target, item_id) not in items:
                errors.append(f"{spec.name}: Resolves {reference}, but {label(target)} has no item {item_id}")
            elif spec.id not in [entry["id"] for entry in items[(target, item_id)]["resolved_by"]]:
                items[(target, item_id)]["resolved_by"].append({"id": spec.id, "name": spec.name, "title": spec.title, "status": spec.status})
    for item in items.values():
        item["status"] = "resolved" if item["resolved_by"] else "open"
    return list(items.values()), errors


def query(catalog: Catalog, kind: str, include_all: bool) -> list[dict[str, Any]]:
    """Items of one type. By default only open ones in specs that are not superseded (a superseding spec restates what still applies)."""
    items, _ = collect(catalog)
    return [item for item in items if item["type"] == kind
            and (include_all or (item["status"] == "open" and item["spec_status"] != "superseded"))]


def counts(catalog: Catalog) -> dict[str, int]:
    open_items = [item for item in collect(catalog)[0] if item["status"] == "open" and item["spec_status"] != "superseded"]
    return {kind: sum(item["type"] == kind for item in open_items) for kind in PREFIXES}


def item_line(item: dict[str, Any]) -> str:
    resolved = ", ".join(label(entry["id"]) for entry in item["resolved_by"])
    tail = f" -> resolved by {resolved}" if resolved else ""
    detail = f": {item['detail']}" if item["detail"] else ""
    return f"{label(item['spec'])}:{item['id']} {item['title']}{detail}{tail}"
