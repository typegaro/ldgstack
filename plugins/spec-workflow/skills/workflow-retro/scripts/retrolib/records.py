"""Effectiveness data from tracker records, the archive manifest, and spec sizes."""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "spec-tracker" / "scripts"))

from tracker import requirements  # noqa: E402

FINDER_ROLES = ("reviewer", "tester", "fixer", "implementer", "parent")


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def spec_sizes(root: Path) -> dict[int, int]:
    sizes: dict[int, int] = {}
    for path in sorted((root / "specs").glob("*.md")):
        number = requirements.spec_number(path)
        if number is not None:
            sizes[number] = sum(1 for item in requirements.parse(path.read_text(encoding="utf-8")) if item.text)
    return sizes


def record_summary(record: dict[str, Any], archived: bool) -> dict[str, Any]:
    bugs = record.get("bugs") or []
    checks = record.get("checks") or []
    return {
        "feature": record.get("feature", ""),
        "archived": archived,
        "status": record.get("status", ""),
        "requirements": len(record.get("requirements") or []),
        "parent_attested": sum(1 for item in record.get("requirements") or [] if item.get("parent_attested")),
        "bugs": len(bugs),
        "bugs_by_finder": dict(sorted(Counter(str(item.get("found_by", "unknown")) for item in bugs).items())),
        "bugs_by_severity": dict(sorted(Counter(str(item.get("severity", "unknown")) for item in bugs).items())),
        "bugs_closed_not_a_bug": sum(1 for item in bugs if item.get("status") == "closed_not_a_bug"),
        "reopens": sum(str(item.get("evidence", "")).count("| Reopened:") for item in bugs),
        "bugs_reopened": sum(1 for item in bugs if "| Reopened:" in str(item.get("evidence", ""))),
        "checks_by_result": dict(sorted(Counter(str(item.get("result", "")) for item in checks).items())),
        "waivers": sum(1 for item in checks if item.get("result") == "waived"),
        "blockers": len(record.get("blockers") or []),
        "tool_gaps": len(record.get("tool_gaps") or []),
        "tool_gaps_deferred": sum(1 for item in record.get("tool_gaps") or [] if item.get("status") == "deferred"),
        "spec_syncs": len((record.get("specification") or {}).get("history") or []),
        "review_skipped": bool((record.get("handoff") or {}).get("review_skipped")),
    }


def load(root: Path) -> dict[str, Any]:
    records: dict[int, dict[str, Any]] = {}
    for archived, directory in ((True, "archive"), (False, "active")):
        for path in sorted((root / "implementation" / directory).glob("*.json")):
            record = read_json(path)
            number = requirements.spec_number(path)
            if isinstance(record, dict) and number is not None:
                records[number] = record_summary(record, archived)
    manifest = read_json(root / "implementation" / "spec-archive.json") or {}
    restores: Counter = Counter()
    for item in manifest.get("history") or []:
        if isinstance(item, dict) and item.get("action") == "restore":
            number = requirements.spec_number(Path(str(item.get("specification", ""))))
            if number is not None:
                restores[number] += 1
    for number, count in restores.items():
        records.setdefault(number, {"feature": "", "archived": True})["restores"] = count
    return {"records": records, "spec_sizes": spec_sizes(root) if (root / "specs").is_dir() else {}}
