"""Strict parser and serializer for the tool-generated spec frontmatter."""
from __future__ import annotations

import re
from typing import Any

from .errors import SpecError

DELIMITER = "---"
KINDS = ("feature", "change", "removal", "convention", "decision")
RELATIONS = ("depends_on", "amends", "supersedes", "references")
KEYS = ("id", "slug", "title", "kind", "created", *RELATIONS)
# Optional: the plugin version that created the spec (from 0.7.1). Older specs have none; rules keyed on it stay warnings for them.
OPTIONAL = "workflow"
KEYS_WITH_WORKFLOW = ("id", "slug", "title", "kind", "created", OPTIONAL, *RELATIONS)
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
INTEGER = re.compile(r"0|[1-9][0-9]*")
DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")

Meta = dict[str, Any]


def has_frontmatter(text: str) -> bool:
    return text.startswith(DELIMITER + "\n")


def split(text: str) -> tuple[list[str], str]:
    """Return the frontmatter lines and the body that follows the closing delimiter."""
    if not has_frontmatter(text):
        raise SpecError("frontmatter is missing")
    lines = text.split("\n")
    try:
        end = lines.index(DELIMITER, 1)
    except ValueError as error:
        raise SpecError("frontmatter is not closed") from error
    return lines[1:end], "\n".join(lines[end + 1:])


def parse_int_list(value: str) -> list[int]:
    if not (value.startswith("[") and value.endswith("]")):
        raise SpecError(f"expected an integer list like [1, 2], got: {value}")
    inner = value[1:-1]
    if not inner:
        return []
    items = inner.split(", ")
    if not all(INTEGER.fullmatch(item) for item in items):
        raise SpecError(f"expected an integer list like [1, 2], got: {value}")
    numbers = [int(item) for item in items]
    if numbers != sorted(set(numbers)):
        raise SpecError(f"list must be sorted without duplicates: {value}")
    return numbers


def parse_value(key: str, value: str) -> Any:
    if key == "id":
        if not INTEGER.fullmatch(value):
            raise SpecError(f"id must be a non-negative integer, got: {value}")
        return int(value)
    if key in RELATIONS:
        return parse_int_list(value)
    if not value or value != value.strip():
        raise SpecError(f"{key} must be a non-empty value without surrounding spaces")
    if key == "slug" and not SLUG.fullmatch(value):
        raise SpecError(f"slug must be lowercase kebab-case, got: {value}")
    if key == "kind" and value not in KINDS:
        raise SpecError(f"kind must be one of {', '.join(KINDS)}, got: {value}")
    if key == "created" and not DATE.fullmatch(value):
        raise SpecError(f"created must be YYYY-MM-DD, got: {value}")
    if key == OPTIONAL and not VERSION.fullmatch(value):
        raise SpecError(f"workflow must be a plugin version like 0.7.1, got: {value}")
    return value


def version_tuple(value: str | None) -> tuple[int, ...]:
    return tuple(int(part) for part in value.split(".")) if value and VERSION.fullmatch(value) else ()


def parse(text: str) -> tuple[Meta, str]:
    lines, body = split(text)
    keys = [line.split(":", 1)[0] for line in lines]
    expected = KEYS_WITH_WORKFLOW if OPTIONAL in keys else KEYS
    if keys != list(expected):
        raise SpecError(f"frontmatter keys must be exactly, in order: {', '.join(KEYS)} (optional {OPTIONAL} after created)")
    meta: Meta = {}
    for key, line in zip(expected, lines):
        prefix = f"{key}: "
        if not line.startswith(prefix):
            raise SpecError(f"frontmatter line must be '{prefix}<value>': {line}")
        meta[key] = parse_value(key, line[len(prefix):])
    if serialize(meta) + body != text:
        raise SpecError("frontmatter is not in canonical form")
    return meta, body


def format_value(key: str, value: Any) -> str:
    if key in RELATIONS:
        return "[" + ", ".join(str(item) for item in value) + "]"
    return str(value)


def serialize(meta: Meta) -> str:
    keys = KEYS_WITH_WORKFLOW if meta.get(OPTIONAL) else KEYS
    lines = [DELIMITER, *(f"{key}: {format_value(key, meta[key])}" for key in keys), DELIMITER]
    return "\n".join(lines) + "\n"


def normalize_title(title: str) -> str:
    cleaned = " ".join(title.split())
    if not cleaned:
        raise SpecError("title must not be empty")
    return cleaned
