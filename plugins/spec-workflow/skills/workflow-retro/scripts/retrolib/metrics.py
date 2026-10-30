"""Deterministic metrics per agent run, spec, and role."""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from typing import Any

from .transcripts import WEIGHTS, Run, ToolCall

# Relative price per model family (Opus = 1.0), applied on top of the token weights; see references/model-prices.md.
MODEL_PRICES = {"opus": 1.0, "sonnet": 0.6, "haiku": 0.2}

BOOKKEEPING_TOOLS = {"Skill", "ToolSearch", "Read", "Grep", "Glob", "Bash"}
READ_TOOLS = {"Read", "Grep", "Glob"}
WORK_CATEGORIES = {"test", "lint", "build", "http", "inspect"}
BOOKKEEPING_COMMANDS = {"tracker", "spec-cli", "read", "git"}
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
TIMED_CATEGORIES = ("test", "build", "lint")  # Bash wall time is reported for these, everything else is "other"
PREFIXED = re.compile(r"\bdirenv exec\b|\bnix (develop|shell)\b|\bnix-shell\b")
ZSH_SPLIT = re.compile(r"\b\w+=[\"'][^\"']*\s[^\"']*[\"']\s*(;|&&)\s*\$\w+")


def seconds(start: str, end: str) -> int:
    try:
        parse = lambda value: datetime.fromisoformat(value.replace("Z", "+00:00"))  # noqa: E731
        return max(0, int((parse(end) - parse(start)).total_seconds()))
    except ValueError:
        return 0


def carry(run: Run, tokens: int, position: int) -> int:
    """Weighted cost of putting tokens into context at an API call: one cache write, then a cache read per later call."""
    later = max(0, run.api_calls - position - 1)
    return int(tokens * WEIGHTS["cache_creation"] + tokens * WEIGHTS["cache_read"] * later)


def weighted(usage: dict[str, int]) -> int:
    return int(sum(usage[key] * weight for key, weight in WEIGHTS.items()))


def adhoc_scripts(run: Run, project: str) -> dict[str, Any]:
    """Script files written outside the project (scratchpad, /tmp): throwaway tools a toolkit tool would replace.
    Names are normalized basenames without digits (s1.py and s2.py both count as s.py)."""
    root = project.rstrip("/") + "/" if project else ""
    found = [call for call in run.calls if call.script.startswith("/") and not (root and call.script.startswith(root))]
    return {
        "count": len(found),
        "tokens": sum(call.script_tokens for call in found),
        "carry": sum(int(call.script_tokens * 5) + carry(run, call.script_tokens, call.position) for call in found),
        "names": sorted({script_name(call.script) for call in found}),
    }


def script_name(path: str) -> str:
    return re.sub(r"[0-9]+", "", path.rsplit("/", 1)[-1].lower())


def family(model: str) -> str:
    lowered = model.lower()
    return next((name for name in MODEL_PRICES if name in lowered), lowered or "unknown")


def model_usage(run: Run, prices: dict[str, float]) -> dict[str, dict[str, Any]]:
    """Per model: API usage, weighted tokens, and cost units (weighted × the family's relative price; unknown = 1.0)."""
    found = {}
    for model, usage in sorted(run.usage_by_model.items()):
        name = family(model)
        tokens = weighted(usage)
        price = prices.get(name, 1.0)
        found[model] = {"family": name, "weighted": tokens, "price": price, "cost": int(tokens * price), "output": usage["output"]}
    return found


def run_metrics(run: Run, large_tokens: int, project: str = "", prices: dict[str, float] | None = None) -> dict[str, Any]:
    models = model_usage(run, prices or MODEL_PRICES)
    calls = run.calls
    processed = sum(run.usage.values())
    prompt = run.usage["input"] + run.usage["cache_read"] + run.usage["cache_creation"]
    bash = [call for call in calls if call.name == "Bash"]
    failures = [call for call in bash if call.exit_code not in (None, 0)]
    commands = Counter(call.command for call in bash)
    retried = sum(1 for previous, current in zip(bash, bash[1:]) if previous.exit_code not in (None, 0) and current.command == previous.command)
    reads: dict[str, list[ToolCall]] = {}
    for call in calls:
        if call.name == "Read":
            reads.setdefault(call.read_key, []).append(call)
    duplicates = [call for group in reads.values() for call in group[1:]]
    per_path = Counter(call.path for call in calls if call.name == "Read")
    per_path.update(path for call in bash for path in call.paths)
    large = [call for call in calls if call.result_tokens >= large_tokens]
    skill_carry = sum(carry(run, tokens, run.skill_positions.get(name, 0)) for name, tokens in run.skill_tokens.items())
    categories = Counter(call.category for call in bash)
    return {
        "id": run.id, "kind": run.kind, "session": run.session, "role": run.role, "agent_type": run.agent_type,
        "description": run.description, "spec": run.spec, "start": run.start, "end": run.end, "plugin_dev": run.plugin_dev,
        "models": models, "cost": sum(item["cost"] for item in models.values()),
        "wall_seconds": seconds(run.start, run.end) if run.start else 0,
        **timing(run),
        "api_calls": run.api_calls, "tool_calls": len(calls),
        "tools": dict(sorted(Counter(call.name for call in calls).items())),
        "bash_categories": dict(sorted(categories.items())),
        "tokens": {
            **run.usage, "processed": processed, "weighted": weighted(run.usage),
            "final_context": run.final_context,
            "cache_read_ratio": round(run.usage["cache_read"] / prompt, 4) if prompt else 0.0,
        },
        "skills": {"loads": dict(sorted(run.skill_tokens.items())), "carry": skill_carry},
        "bash": {
            "failures": len(failures),
            "exit_codes": dict(sorted(Counter(str(call.exit_code) for call in failures).items())),
            "repeated_commands": sum(count - 1 for count in commands.values() if count > 1),
            "retried_after_failure": retried,
            "failure_carry": sum(carry(run, call.result_tokens, call.position) for call in failures),
        },
        "reads": {
            "total": sum(per_path.values()),
            "duplicates": len(duplicates),
            "duplicate_tokens": sum(call.result_tokens for call in duplicates),
            "duplicate_carry": sum(carry(run, call.result_tokens, call.position) for call in duplicates),
            "hot_paths": [{"path": path, "reads": count} for path, count in sorted(per_path.items(), key=lambda item: (-item[1], item[0])) if count > 2][:5],
            "full_reads_large": sum(1 for call in large if call.name == "Read"),
            **rereads(run),
        },
        "large_results": [
            {"tool": call.name, "category": call.category or call.name, "tokens": call.result_tokens,
             "position": call.position, "carry": carry(run, call.result_tokens, call.position)}
            for call in large
        ],
        "persisted_outputs": sum(1 for call in calls if call.persisted_kb),
        "cli_errors": dict(sorted(Counter(call.cli_error for call in calls if call.cli_error).items())),
        "bash_failure_classes": dict(sorted(Counter(name for name in map(failure_class, failures) if name).items())),
        "api_errors": dict(sorted(run.api_errors.items())),
        "queued_messages": run.queued_messages,
        "notifications": list(run.notifications),
        "resumed": run.kind == "subagent" and (len(run.notifications) > 1 or run.queued_messages > 0),
        "early_stop": run.kind == "subagent" and (
            bool(run.api_errors) or any(status != "completed" for status in run.notifications[-1:]) or run.last_stop_reason not in ("end_turn", "")
        ),
        "bookkeeping_only": bookkeeping_only(run),
        "adhoc_scripts": adhoc_scripts(run, project),
        "turns": turns(run),
        "carry_by_category": dict(sorted(carry_by_category(run).items())),
        "plugin_versions": sorted(run.plugin_versions),
        "reports_received": {"count": len(run.report_tokens), "tokens": sum(run.report_tokens), "max": max(run.report_tokens, default=0)},
    }


def timing(run: Run) -> dict[str, Any]:
    """Active time = API call durations (request to last response line) + tool time per turn (first tool_use to last
    tool_result, so parallel calls count once). Idle gaps between resumes count only in wall_seconds."""
    api = sum(seconds(start, end) for start, end in run.api_spans)
    turns: dict[int, list[ToolCall]] = {}
    for call in run.calls:
        if call.started and call.finished:
            turns.setdefault(call.position, []).append(call)
    tools = sum(seconds(min(call.started for call in group), max(call.finished for call in group)) for group in turns.values())
    bash: Counter = Counter(dict.fromkeys((*TIMED_CATEGORIES, "other"), 0))
    for call in run.calls:
        if call.name == "Bash" and call.started and call.finished:
            bash[call.category if call.category in TIMED_CATEGORIES else "other"] += seconds(call.started, call.finished)
    return {"active_seconds": api + tools, "api_seconds": api, "tool_seconds": tools, "bash_seconds": dict(sorted(bash.items()))}


def failure_class(call: ToolCall) -> str | None:
    """Known shell mistakes with a fix hint in the bash.failures finding (#61)."""
    if call.exit_code == 144 and "pkill -f" in call.command:
        return "pkill-self-match"
    if call.exit_code == 127:
        if ZSH_SPLIT.search(call.command):
            return "zsh-word-split"
        return "command-not-found" if PREFIXED.search(call.command) else "missing-env-prefix"
    return None


def rereads(run: Run) -> dict[str, int]:
    """Read calls (Read tool or Bash cat/sed/grep) touching a file this run already read."""
    seen: set[str] = set()
    count = carried = 0
    for call in run.calls:
        paths = [call.path] if call.name == "Read" else call.paths
        if not paths:
            continue
        if any(path in seen for path in paths):
            count += 1
            carried += carry(run, call.result_tokens, call.position)
        seen.update(paths)
    return {"rereads": count, "reread_carry": carried}


def is_read(call: ToolCall) -> bool:
    return call.name in READ_TOOLS or (call.name == "Bash" and call.category == "read")


def is_work(call: ToolCall) -> bool:
    return call.name in EDIT_TOOLS or (call.name == "Bash" and call.category in WORK_CATEGORIES)


def carry_by_category(run: Run) -> Counter:
    found: Counter = Counter()
    for call in run.calls:
        found[call.category or call.name] += carry(run, call.result_tokens, call.position)
    return found


def turns(run: Run) -> dict[str, Any]:
    """Turn shape: tool calls per API call, read-only turns that directly follow another (batchable), onboarding cost."""
    per_turn: dict[int, list[ToolCall]] = {}
    for call in run.calls:
        per_turn.setdefault(call.position, []).append(call)
    read_turns = [position for position, group in sorted(per_turn.items()) if all(is_read(call) for call in group)]
    batchable = sum(1 for previous, current in zip(read_turns, read_turns[1:]) if current == previous + 1)
    first_work = next((call.position for call in run.calls if is_work(call)), run.api_calls)
    weights = run.call_weights
    return {
        "tool_calls_per_api_call": round(len(run.calls) / run.api_calls, 3) if run.api_calls else 0.0,
        "read_only_turns": len(read_turns),
        "batchable_turns": batchable,
        "mean_call_weighted": sum(weights) // len(weights) if weights else 0,
        "onboarding_calls": min(first_work + 1, run.api_calls),
        "onboarding_weighted": sum(weights[: first_work + 1]),
    }


def bookkeeping_only(run: Run) -> bool:
    """A spec-role run that changed no file and ran only tracker, spec, read, or git commands."""
    if run.kind != "subagent" or run.role not in ("implementer", "reviewer", "tester", "fixer") or not run.calls:
        return False
    if any(call.name not in BOOKKEEPING_TOOLS for call in run.calls):
        return False
    bash = [call for call in run.calls if call.name == "Bash"]
    return any(call.category == "tracker" for call in bash) and all(call.category in BOOKKEEPING_COMMANDS for call in bash)


def total(runs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "runs": len(runs),
        "api_calls": sum(run["api_calls"] for run in runs),
        "tool_calls": sum(run["tool_calls"] for run in runs),
        "wall_seconds": sum(run["wall_seconds"] for run in runs),
        "active_seconds": sum(run.get("active_seconds", 0) for run in runs),
        "test_build_seconds": sum(test_build_seconds(run) for run in runs),
        "processed_tokens": sum(run["tokens"]["processed"] for run in runs),
        "weighted_tokens": sum(run["tokens"]["weighted"] for run in runs),
        "cost_units": sum(run.get("cost", 0) for run in runs),
        "output_tokens": sum(run["tokens"]["output"] for run in runs),
        "final_context_tokens": sum(run["tokens"]["final_context"] for run in runs),
        "cache_read_ratio": cache_ratio(runs),
    }


def test_build_seconds(run: dict[str, Any]) -> int:
    seconds_by = run.get("bash_seconds") or {}
    return int(seconds_by.get("test", 0) + seconds_by.get("build", 0))


def cache_ratio(runs: list[dict[str, Any]]) -> float:
    read = sum(run["tokens"]["cache_read"] for run in runs)
    prompt = sum(run["tokens"]["cache_read"] + run["tokens"]["cache_creation"] + run["tokens"]["input"] for run in runs)
    return round(read / prompt, 4) if prompt else 0.0


def by_spec(runs: list[dict[str, Any]], data: dict[str, Any]) -> list[dict[str, Any]]:
    numbers = sorted({run["spec"] for run in runs if run["spec"] is not None} | set(data["records"]))
    found = []
    for number in numbers:
        own = [run for run in runs if run["spec"] == number and run["kind"] == "subagent"]
        if not own:
            continue
        # The record's tracked requirements (parent-added and amended ones included) beat the spec's R<n> count.
        size = (data["records"].get(number) or {}).get("requirements") or data["spec_sizes"].get(number, 0)
        totals = total(own)
        found.append({
            "spec": number, "requirements": size, **totals,
            "runs_by_role": dict(sorted(Counter(run["role"] for run in own).items())),
            "weighted_per_requirement": totals["weighted_tokens"] // size if size else None,
            "final_context_per_requirement": totals["final_context_tokens"] // size if size else None,
            "record": data["records"].get(number),
        })
    return found


def by_role(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    roles = sorted({run["role"] for run in runs})
    found = []
    for role in roles:
        own = [run for run in runs if run["role"] == role]
        totals = total(own)
        found.append({
            "role": role, **totals,
            "mean_weighted_tokens": totals["weighted_tokens"] // len(own),
            "mean_final_context": totals["final_context_tokens"] // len(own),
            "mean_tool_calls": round(totals["tool_calls"] / len(own), 1),
            "skill_carry": sum(run["skills"]["carry"] for run in own),
            "bash_failures": sum(run["bash"]["failures"] for run in own),
            "duplicate_reads": sum(run["reads"]["duplicates"] for run in own),
            "large_results": sum(len(run["large_results"]) for run in own),
            "adhoc_scripts": sum(run["adhoc_scripts"]["count"] for run in own),
        })
    return found


def by_model(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cost by model and role: the planner/executor split shows up as Opus vs Sonnet weighted tokens."""
    rows: dict[str, dict[str, Any]] = {}
    for run in runs:
        for model, item in run.get("models", {}).items():
            row = rows.setdefault(model, {"model": model, "family": item["family"], "price": item["price"], "runs": 0,
                                          "weighted_tokens": 0, "cost_units": 0, "roles": Counter()})
            row["runs"] += 1
            row["weighted_tokens"] += item["weighted"]
            row["cost_units"] += item["cost"]
            row["roles"][run["role"]] += 1
    return [{**row, "roles": dict(sorted(row["roles"].items()))} for row in sorted(rows.values(), key=lambda row: -row["cost_units"])]


def effectiveness(data: dict[str, Any], specs: set[int] | None = None) -> dict[str, Any]:
    """Bug and check outcomes over the given specs' records (all records when specs is None)."""
    chosen = {number: item for number, item in data["records"].items() if specs is None or number in specs}
    records = [item for item in chosen.values() if "bugs" in item]
    finders: Counter = Counter()
    for item in records:
        finders.update(item["bugs_by_finder"])
    return {
        "records": len(records),
        "bugs": sum(item["bugs"] for item in records),
        "bugs_by_finder": dict(sorted(finders.items())),
        "bugs_by_severity": dict(sorted(sum((Counter(item["bugs_by_severity"]) for item in records), Counter()).items())),
        "closed_not_a_bug": sum(item["bugs_closed_not_a_bug"] for item in records),
        "reopens": sum(item["reopens"] for item in records),
        "waivers": sum(item["waivers"] for item in records),
        "blockers": sum(item["blockers"] for item in records),
        "tool_gaps": sum(item.get("tool_gaps", 0) for item in records),
        "tool_gaps_deferred": sum(item.get("tool_gaps_deferred", 0) for item in records),
        "restored_after_acceptance": sum(item.get("restores", 0) for item in chosen.values()),
    }
