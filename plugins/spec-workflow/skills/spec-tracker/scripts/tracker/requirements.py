"""Parse `- **R<n>** [tag] text` requirement bullets and their cross-spec references from spec Markdown."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

BULLET = re.compile(r"^(\s*)[-*] \*\*R([0-9]+[a-z]?)\*\*(.*)$")
FENCE = re.compile(r"^\s*(```|~~~)")
LIST_ITEM = re.compile(r"^(\s*)[-*+] ")
SPEC_NUMBER = re.compile(r"^([0-9]+)-")
VERB = re.compile(r"\b(replaces|amends|removes)\b", re.IGNORECASE)
REFERENCE = re.compile(r"(?:\b([0-9]+):)?\bR([0-9]+[a-z]?)(?:\s*[-–]\s*R?([0-9]+)\b)?")
REFERENCE_END = re.compile(r"[);]|\.\s|\.$|\b(replaces|amends|removes)\b", re.IGNORECASE)


@dataclass
class Requirement:
    id: str
    text: str


@dataclass
class Reference:
    verb: str
    spec: int
    requirement: str
    source: str

    @property
    def ref(self) -> str:
        return f"{self.spec}:R{self.requirement}"


def strip_markdown(text: str) -> str:
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"(\*\*|__|`)", "", text)
    return " ".join(text.split())


def parse(markdown: str) -> list[Requirement]:
    """Requirement bullets outside code fences; indented continuation lines and nested items join the text."""
    found: list[Requirement] = []
    lines = markdown.split("\n")
    fenced = False
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        if FENCE.match(line):
            fenced = not fenced
            continue
        match = None if fenced else BULLET.match(line)
        if not match:
            continue
        indent = len(match.group(1))
        parts = [match.group(3)]
        while index < len(lines):
            following = lines[index]
            if not following.strip() or FENCE.match(following):
                break
            item = LIST_ITEM.match(following)
            if item and len(item.group(1)) <= indent:
                break
            if not item and len(following) - len(following.lstrip()) <= indent:
                break
            parts.append(following)
            index += 1
        found.append(Requirement(match.group(2), strip_markdown(" ".join(parts))))
    return found


TESTABILITY = re.compile(r"^##\s+Testability\s*$")
SECTION_END = re.compile(r"^#{1,2}\s")


def testability_ids(markdown: str) -> set[str]:
    """R<n> ids listed under the spec's `## Testability` heading (outside code fences)."""
    found: set[str] = set()
    inside = fenced = False
    for line in markdown.split("\n"):
        if FENCE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        if TESTABILITY.match(line):
            inside = True
            continue
        if SECTION_END.match(line):
            inside = False
            continue
        match = BULLET.match(line) if inside else None
        if match:
            found.add(match.group(2))
    return found


def has_requirements(markdown: str) -> bool:
    return any(item.text for item in parse(markdown))


def spec_number(path: Path) -> int | None:
    match = SPEC_NUMBER.match(path.name)
    return int(match.group(1)) if match else None


def references(requirement: Requirement) -> list[Reference]:
    """`replaces 3:R11`, `amends 22:R7, R9`, `replaces ... 6:R6 and 9:R7-R9`: ids carry forward; ranges expand."""
    found: list[Reference] = []
    text = requirement.text
    for verb in VERB.finditer(text):
        rest = text[verb.end():]
        end = REFERENCE_END.search(rest)
        chunk = rest[: end.start()] if end else rest
        current: int | None = None
        for match in REFERENCE.finditer(chunk):
            if match.group(1):
                current = int(match.group(1))
            if current is None:
                continue
            start, stop = match.group(2), match.group(3)
            numbers = [start]
            if stop and start.isdigit() and int(stop) > int(start):
                numbers = [str(number) for number in range(int(start), int(stop) + 1)]
            found.extend(Reference(verb.group(1).lower(), current, number, requirement.id) for number in numbers)
    unique: dict[str, Reference] = {}
    for item in found:
        unique.setdefault(item.ref, item)
    return list(unique.values())
