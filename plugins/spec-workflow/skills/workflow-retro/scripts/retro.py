#!/usr/bin/env python3
"""Deterministic retrospective of spec-workflow runs from Claude Code transcripts and tracker records. Read-only."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

from retrolib import conformance, findings, metrics, records, redact, render, transcripts

SCHEMA_VERSION = 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Measure spec-workflow runs and rank improvements")
    parser.add_argument("--project", type=Path, help="project root with specs/ and implementation/ (default: cwd)")
    parser.add_argument("--transcripts", type=Path, help="Claude Code project transcript dir (default: ~/.claude/projects/<slug>)")
    parser.add_argument("--session", action="append", default=[], help="limit to these session IDs")
    parser.add_argument("--since", default="", help="ISO date/time; runs ending before it are skipped")
    parser.add_argument("--until", default="", help="ISO date/time; runs starting after it are skipped")
    parser.add_argument("--large-tokens", type=int, default=5000, help="tool results at or above this size are large")
    parser.add_argument("--top", type=int, default=10)
    parser.add_argument("--label", default="", help="report label, e.g. the plugin version")
    parser.add_argument("--compare", type=Path, help="earlier report JSON to compare against")
    parser.add_argument("--out-dir", type=Path, help="write retro.json and retro.md here")
    parser.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    parser.add_argument("--conformance", action="store_true", help="also check workflow-rule conformance (early starts, lanes, briefs, ...)")
    parser.add_argument("--model-weight", action="append", default=[], metavar="FAMILY=W",
                        help="relative price of a model family (default opus=1.0 sonnet=0.6 haiku=0.2); repeatable")
    return parser.parse_args()


def slug(path: Path) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def in_window(run: transcripts.Run, since: str, until: str) -> bool:
    if not run.start:
        return False
    return (not since or run.end >= since) and (not until or run.start <= until)


def compare(report: dict[str, Any], path: Path) -> dict[str, Any]:
    old = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for scope in ("subagents", "parent"):
        for key in ("runs", "processed_tokens", "weighted_tokens", "final_context_tokens", "tool_calls"):
            before, after = old.get("totals", {}).get(scope, {}).get(key), report["totals"][scope][key]
            rows.append(delta(f"{scope}.{key}", before, after))
    old_roles = {item["role"]: item for item in old.get("by_role", [])}
    for item in report["by_role"]:
        rows.append(delta(f"{item['role']}.mean_weighted_tokens", old_roles.get(item["role"], {}).get("mean_weighted_tokens"), item["mean_weighted_tokens"]))
    old_keys = {item["key"] for item in old.get("findings", [])}
    new_keys = {item["key"] for item in report["findings"]}
    return {"against": old.get("label", ""), "metrics": rows,
            "new_findings": sorted(new_keys - old_keys), "resolved_findings": sorted(old_keys - new_keys)}


def delta(metric: str, before: Any, after: Any) -> dict[str, Any]:
    change = None
    if isinstance(before, (int, float)) and isinstance(after, (int, float)) and before:
        change = f"{(after - before) / before:+.1%}"
    return {"metric": metric, "before": before, "after": after, "change": change}


def prices(values: list[str]) -> dict[str, float]:
    found = dict(metrics.MODEL_PRICES)
    for value in values:
        name, _, weight = value.partition("=")
        try:
            found[name.strip().lower()] = float(weight)
        except ValueError:
            raise SystemExit(f"error: --model-weight wants FAMILY=NUMBER, got {value!r}") from None
    return found


def build(args: argparse.Namespace) -> dict[str, Any]:
    project = (args.project or Path.cwd()).resolve()
    directory = (args.transcripts or Path.home() / ".claude" / "projects" / slug(project)).expanduser()
    if not directory.is_dir():
        raise SystemExit(f"error: transcript directory not found: {directory}")
    data = records.load(project)
    loaded = transcripts.load(directory, set(args.session) or None, args.since, args.until)
    runs = [run for run in loaded if in_window(run, args.since, args.until)]
    weights = prices(args.model_weight)
    measured = [metrics.run_metrics(run, args.large_tokens, str(project), weights) for run in runs]
    for item in measured:
        if data["spec_sizes"] and item["spec"] not in data["spec_sizes"]:
            item["spec"] = None
    # Tagged plugin-development runs are reported separately, never as workflow cost.
    dev = [item for item in measured if item["plugin_dev"]]
    workflow = [item for item in measured if not item["plugin_dev"]]
    agents = [item for item in workflow if item["kind"] == "subagent"]
    parent = [item for item in workflow if item["kind"] == "main"]
    report = {
        "schema_version": SCHEMA_VERSION, "label": args.label,
        "inputs": {"project": str(project), "transcripts": str(directory), "sessions": sorted({run.session for run in runs}),
                   "since": args.since, "until": args.until, "run_count": len(runs), "large_tokens": args.large_tokens,
                   "model_prices": weights},
        "totals": {"subagents": metrics.total(agents), "parent": metrics.total(parent), "plugin_dev": metrics.total(dev)},
        "by_model": metrics.by_model(workflow),
        "by_spec": metrics.by_spec(agents, data),
        "by_role": metrics.by_role(agents),
        "effectiveness": metrics.effectiveness(data, {item["spec"] for item in agents if item["spec"] is not None}),
        "effectiveness_project": metrics.effectiveness(data),
        "findings": findings.build(workflow, args.top),
        "runs": measured,
    }
    if args.conformance:
        report["conformance"] = conformance.build(project, runs, measured)
    if args.compare:
        report["comparison"] = compare(report, args.compare)
    return redact.walk(report)


def main() -> int:
    args = parse_args()
    report = build(args)
    serialized = json.dumps(report, indent=2, sort_keys=True) + "\n"
    text = render.markdown(report)
    if args.out_dir:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        (args.out_dir / "retro.json").write_text(serialized, encoding="utf-8")
        (args.out_dir / "retro.md").write_text(text, encoding="utf-8")
    sys.stdout.write(serialized if args.json else text)
    return 0


if __name__ == "__main__":
    os.environ.setdefault("TZ", "UTC")
    raise SystemExit(main())
