"""Computed history views: show, effective spec, log, and graph."""
from __future__ import annotations

from typing import Any

from .catalog import Catalog, Spec, label
from .frontmatter import RELATIONS

Edge = tuple[int, int, str]
OVERRIDES = ("amends", "supersedes")


def edges(catalog: Catalog) -> list[Edge]:
    found = []
    for spec in catalog.ordered():
        for relation in RELATIONS:
            found.extend((spec.id, target, relation) for target in spec.relations[relation] if target in catalog.specs)
    return sorted(found)


def edge_dict(edge: Edge) -> dict[str, Any]:
    return {"from": edge[0], "to": edge[1], "type": edge[2]}


def read_text(spec: Spec) -> str:
    return spec.path.read_text(encoding="utf-8")


def show(catalog: Catalog, spec: Spec) -> dict[str, Any]:
    return {**spec.summary(catalog.root), "content": read_text(spec)}


def overrides_of(spec: Spec, members: set[int]) -> str:
    parts = []
    for relation in OVERRIDES:
        targets = [label(target) for target in spec.relations[relation] if target in members]
        if targets:
            parts.append(f"{relation} {', '.join(targets)}")
    return "; ".join(parts)


def effective(catalog: Catalog, spec: Spec) -> list[dict[str, Any]]:
    """The spec followed by every spec that transitively amends or supersedes it, in id order."""
    members = {spec.id}
    for candidate in catalog.ordered():
        if candidate.id > spec.id and any(target in members for relation in OVERRIDES for target in candidate.relations[relation]):
            members.add(candidate.id)
    parts = []
    for member in sorted(members):
        item = catalog.specs[member]
        relation = "self" if member == spec.id else overrides_of(item, members)
        parts.append({"id": member, "relation": relation, "path": item.path.relative_to(catalog.root).as_posix(), "content": read_text(item)})
    return parts


def effective_text(parts: list[dict[str, Any]]) -> str:
    chunks = []
    for part in parts:
        suffix = "" if part["relation"] == "self" else f" {part['relation']}"
        content = part["content"].rstrip("\n")
        chunks.append(f"<!-- spec {label(part['id'])}{suffix} -->\n{content}\n")
    return "\n".join(chunks)


def walk(catalog: Catalog, start: int, outgoing: bool) -> list[dict[str, Any]]:
    all_edges = edges(catalog)
    visited, frontier, found = {start}, [start], []
    while frontier:
        current = frontier.pop()
        for edge in all_edges:
            source, target = (edge[0], edge[1]) if outgoing else (edge[1], edge[0])
            if source != current:
                continue
            found.append(edge)
            if target not in visited:
                visited.add(target)
                frontier.append(target)
    nodes = []
    for node in sorted(visited - {start}):
        spec = catalog.specs[node]
        links = sorted({edge for edge in found if (edge[1] if outgoing else edge[0]) == node})
        nodes.append({"id": node, "name": spec.name, "title": spec.title, "kind": spec.kind, "status": spec.status,
                      "links": [edge_dict(edge) for edge in links]})
    return nodes


def log(catalog: Catalog, spec: Spec, manifest: dict[str, Any] | None = None) -> dict[str, Any]:
    history = [item for item in (manifest or {}).get("history", []) if item.get("specification") == spec.name]
    return {"spec": spec.summary(catalog.root), "ancestors": walk(catalog, spec.id, True), "descendants": walk(catalog, spec.id, False),
            "history": [{key: item[key] for key in ("action", "at", "reason", "user_decision", "conflict", "status_at_edit") if key in item}
                        for item in history]}


def log_text(value: dict[str, Any]) -> str:
    spec = value["spec"]
    lines = [f"{label(spec['id'])} {spec['slug']} [{spec['status']}] {spec['title']}"]
    for section in ("ancestors", "descendants"):
        lines.append(f"{section}:")
        if not value[section]:
            lines.append("  none")
        for node in value[section]:
            links = ", ".join(f"{label(link['from'])} {link['type']} {label(link['to'])}" for link in node["links"])
            lines.append(f"  {node['name']} [{node['status']}] ({links})")
    lines.append("history:")
    for item in value.get("history", []) or [{"action": "none"}]:
        extra = "".join(f" {key}={item[key]!r}" for key in ("reason", "user_decision", "conflict") if key in item)
        lines.append(f"  {item.get('at', '')} {item['action']}{extra}".rstrip())
    return "\n".join(lines)


def graph(catalog: Catalog) -> dict[str, Any]:
    nodes = [
        {"id": spec.id, "slug": spec.slug, "title": spec.title, "kind": spec.kind, "status": spec.status,
         "path": spec.path.relative_to(catalog.root).as_posix()}
        for spec in catalog.ordered()
    ]
    return {"nodes": nodes, "edges": [edge_dict(edge) for edge in edges(catalog)]}


def mermaid(value: dict[str, Any]) -> str:
    lines = ["flowchart TD"]
    for node in value["nodes"]:
        lines.append(f'  s{label(node["id"])}["{label(node["id"])} {node["slug"]} ({node["kind"]}, {node["status"]})"]')
    for edge in value["edges"]:
        lines.append(f"  s{label(edge['from'])} -->|{edge['type']}| s{label(edge['to'])}")
    return "\n".join(lines)
