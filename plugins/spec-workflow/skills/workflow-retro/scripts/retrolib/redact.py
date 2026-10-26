"""Last-line redaction of every string the report emits (paths, command snippets, descriptions)."""
from __future__ import annotations

import re
from typing import Any

PATTERNS = (
    re.compile(r"\b(sk|pk|rk)-[A-Za-z0-9_-]{12,}"),
    re.compile(r"\b(ghp|gho|ghu|ghs|github_pat|xox[abpr]|glpat)[-_][A-Za-z0-9_-]{10,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    re.compile(r"(?i)\b(bearer|token|basic)\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(r"(?i)\b(password|passwd|secret|api[_-]?key|token|client[_-]?secret)\s*[=:]\s*\S+"),
    re.compile(r"(?i)(postgres(ql)?|mysql|redis|mongodb)://[^\s'\"]+"),
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    re.compile(r"\b[A-Fa-f0-9]{32,}\b"),
    re.compile(r"\b[A-Za-z0-9+/]{40,}={0,2}"),
)
LIMIT = 400


def text(value: str) -> str:
    for pattern in PATTERNS:
        value = pattern.sub("[redacted]", value)
    return value if len(value) <= LIMIT else value[: LIMIT - 1] + "…"


def walk(value: Any) -> Any:
    if isinstance(value, str):
        return text(value)
    if isinstance(value, list):
        return [walk(item) for item in value]
    if isinstance(value, dict):
        return {key: walk(item) for key, item in value.items()}
    return value
