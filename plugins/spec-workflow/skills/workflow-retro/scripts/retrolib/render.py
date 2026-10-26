"""Markdown view of a retro report."""
from __future__ import annotations

from typing import Any


def number(value: Any) -> str:
    return f"{value:,}" if isinstance(value, int) else ("—" if value is None else str(value))


def table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines.extend("| " + " | ".join(number(cell) for cell in row) + " |" for row in rows)
    return lines


def markdown(report: dict[str, Any]) -> str:
    inputs, totals = report["inputs"], report["totals"]
    lines = [f"# Workflow retro{': ' + report['label'] if report.get('label') else ''}", "",
             f"Runs: {inputs['run_count']} from {len(inputs['sessions'])} session(s); window {inputs['since'] or 'start'} → {inputs['until'] or 'end'}.",
             "Weighted tokens = input + 1.25×cache write + 0.1×cache read + 5×output (relative cost, not dollars). "
             "Final context = Claude Code's `subagent_tokens`.", "", "## Totals", ""]
    lines += table(["scope", "runs", "API calls", "tool calls", "processed", "weighted", "cost units", "final context", "cache read", "wall s"],
                   [[name, item["runs"], item["api_calls"], item["tool_calls"], item["processed_tokens"], item["weighted_tokens"], item.get("cost_units"),
                     item["final_context_tokens"], item["cache_read_ratio"], item["wall_seconds"]] for name, item in totals.items()])
    lines += ["", "## By model", "", f"Cost units = weighted × relative model price {report['inputs'].get('model_prices', {})}.", ""]
    lines += table(["model", "family", "price", "runs", "weighted", "cost units", "roles"],
                   [[item["model"], item["family"], item["price"], item["runs"], item["weighted_tokens"], item["cost_units"],
                     ", ".join(f"{k} {v}" for k, v in item["roles"].items())] for item in report.get("by_model", [])])
    lines += ["", "## By spec", ""]
    lines += table(["spec", "reqs", "runs", "roles", "weighted", "weighted/req", "final context", "bugs (finder)", "reopens"],
                   [[f"{item['spec']:04d}", item["requirements"], item["runs"], ", ".join(f"{k} {v}" for k, v in item["runs_by_role"].items()),
                     item["weighted_tokens"], item["weighted_per_requirement"], item["final_context_tokens"],
                     ", ".join(f"{k} {v}" for k, v in ((item.get("record") or {}).get("bugs_by_finder") or {}).items()) or "—",
                     (item.get("record") or {}).get("reopens")] for item in report["by_spec"]])
    lines += ["", "## By role", ""]
    lines += table(["role", "runs", "mean weighted", "mean final context", "mean tool calls", "skill carry", "bash failures", "dup reads", "large results", "ad hoc scripts"],
                   [[item["role"], item["runs"], item["mean_weighted_tokens"], item["mean_final_context"], item["mean_tool_calls"],
                     item["skill_carry"], item["bash_failures"], item["duplicate_reads"], item["large_results"], item.get("adhoc_scripts", 0)] for item in report["by_role"]])
    effect = report["effectiveness"]
    lines += ["", "## Effectiveness", "",
              f"- Bugs: {effect['bugs']} in {effect['records']} records; by finder: {effect['bugs_by_finder'] or 'none'}; by severity: {effect['bugs_by_severity'] or 'none'}.",
              f"- Reopens: {effect['reopens']}; closed not a bug: {effect['closed_not_a_bug']}; waivers: {effect['waivers']}; blockers: {effect['blockers']}; tool gaps: {effect.get('tool_gaps', 0)} ({effect.get('tool_gaps_deferred', 0)} deferred); restored after acceptance: {effect['restored_after_acceptance']}.",
              f"- Whole project ({report['effectiveness_project']['records']} records): bugs by finder {report['effectiveness_project']['bugs_by_finder'] or 'none'}.",
              "", "## Top improvements", "",
              "Estimates overlap (e.g. batching and long-context both shrink the same late turns); they rank changes and are not additive.", ""]
    for item in report["findings"]:
        lines += [f"### {item['rank']}. {item['title']} (`{item['key']}`)", "",
                  f"- Estimated savings: {item['estimated_savings']:,} weighted tokens over {item['frequency']} occurrences ({item['basis']}).",
                  f"- Change: `{item['skill_file']}`, section \"{item['section']}\": {item['proposal']}",
                  f"- Independence risk: {item['independence_risk']}.", "- Evidence:"]
        lines += [f"  - {line}" for line in item["evidence"]]
        lines.append("")
    checks = report.get("conformance")
    if checks:
        lines += ["## Conformance", ""]
        lines += table(["rule", "violations", "enforced by"], [[f"{item['title']} (`{item['key']}`)", item["violations"], item["enforced_by"]] for item in checks])
        for item in checks:
            if item["evidence"]:
                lines += ["", f"- `{item['key']}`:"] + [f"  - {line}" for line in item["evidence"]]
        lines.append("")
    comparison = report.get("comparison")
    if comparison:
        lines += ["## Comparison", "", f"Against: {comparison['against'] or 'previous report'}", ""]
        lines += table(["metric", "before", "after", "change"], [[row["metric"], row["before"], row["after"], row["change"]] for row in comparison["metrics"]])
        lines += ["", f"- New findings: {', '.join(comparison['new_findings']) or 'none'}",
                  f"- Resolved findings: {', '.join(comparison['resolved_findings']) or 'none'}", ""]
    return "\n".join(lines).rstrip() + "\n"
