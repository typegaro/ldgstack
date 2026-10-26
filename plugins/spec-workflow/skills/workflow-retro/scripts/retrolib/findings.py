"""Ranked improvement findings. Each estimate states its basis; all values are weighted tokens (see WEIGHTS)."""
from __future__ import annotations

from collections import Counter
from typing import Any, Callable

Metrics = dict[str, Any]
Finding = dict[str, Any]

SPEC_ROLES = ("planner", "implementer", "reviewer", "tester", "fixer", "toolsmith")
ROLE_SKILL = {
    "implementer": "skills/spec-implementer/SKILL.md", "fixer": "skills/spec-implementer/SKILL.md",
    "reviewer": "skills/spec-reviewer/SKILL.md", "tester": "skills/spec-tester/SKILL.md",
    "planner": "agents/spec-planner.md", "toolsmith": "agents/spec-toolsmith.md",
    "parent": "skills/spec-orchestrator/SKILL.md", "other": "skills/spec-orchestrator/SKILL.md",
}
CLI_SECTIONS = {
    "role": "Roles and handoffs", "gate": "Gates", "not-run-check": "Gates", "open-bugs": "Roles and handoffs",
    "confirmation": "Roles and handoffs", "spec-hash": "Gates", "unknown-id": "Commands", "usage": "Commands", "other": "Commands",
}
LONG_CONTEXT = 250_000
SPLIT_CALL_WEIGHT = 15_000  # weighted cost of one call at ~150k context
LARGE_RESULT_CAP = 2_000


def label(run: Metrics) -> str:
    spec = f"{run['spec']:04d} " if run["spec"] is not None else ""
    return f"{spec}{run['role']} {run['id'][:8]} ({run['description'][:40]})"


def top(runs: list[Metrics], key: Callable[[Metrics], int], count: int = 3) -> list[str]:
    ranked = sorted((run for run in runs if key(run) > 0), key=lambda run: (-key(run), run["id"]))
    return [f"{label(run)}: {key(run):,}" for run in ranked[:count]]


def roles_of(runs: list[Metrics], key: Callable[[Metrics], int]) -> Counter:
    found: Counter = Counter()
    for run in runs:
        found[run["role"]] += key(run)
    return found


def finding(key: str, title: str, savings: int, frequency: int, basis: str, evidence: list[str], skill: str, section: str,
            proposal: str, risk: str) -> Finding:
    return {
        "key": key, "title": title, "estimated_savings": max(0, int(savings)), "frequency": frequency, "basis": basis,
        "evidence": evidence, "skill_file": skill, "section": section, "proposal": proposal, "independence_risk": risk,
    }


def main_role(counter: Counter) -> str:
    return sorted(counter.items(), key=lambda item: (-item[1], item[0]))[0][0] if counter else "implementer"


def batching(runs: list[Metrics]) -> Finding | None:
    saved = lambda run: int(run["turns"]["batchable_turns"] * run["turns"]["mean_call_weighted"] * 0.9)  # noqa: E731
    turns = sum(run["turns"]["batchable_turns"] for run in runs)
    if not turns:
        return None
    ratio = sum(run["tool_calls"] for run in runs) / max(1, sum(run["api_calls"] for run in runs))
    by_role = roles_of(runs, saved)
    return finding(
        "turns.batching", "Read-only turns run one tool call at a time", sum(saved(run) for run in runs), turns,
        "batchable turns (read-only turn directly after another) x the run's mean weighted cost per API call x 0.9",
        [f"{ratio:.2f} tool calls per API call overall", f"{turns} batchable read-only turns",
         "by role: " + ", ".join(f"{role} {value:,}" for role, value in by_role.most_common()), *top(runs, saved)],
        "agents/*.md and " + ROLE_SKILL[main_role(by_role)], "agent prompt / 1. Establish the assignment",
        "Tell agents to issue independent reads, greps, and status commands as parallel tool calls in one turn, "
        "and to plan the files to read before reading them.", "none",
    )


def rereads(runs: list[Metrics]) -> Finding | None:
    value = lambda run: run["reads"]["reread_carry"]  # noqa: E731
    count = sum(run["reads"]["rereads"] for run in runs)
    if not count:
        return None
    by_role = roles_of(runs, value)
    hot = sorted({f"{item['path']} x{item['reads']}" for run in runs for item in run["reads"]["hot_paths"]})
    return finding(
        "context.rereads", "Files are read again within the same run", int(sum(value(run) for run in runs) * 0.7), count,
        "context carry of reads touching an already-read file x 0.7 (some re-reads follow edits and are needed)",
        [f"{count} re-reads", "by role: " + ", ".join(f"{role} {value:,}" for role, value in by_role.most_common()),
         *top(runs, value), "hot files: " + "; ".join(hot[:6])],
        ROLE_SKILL[main_role(by_role)], "3. Implementation rules",
        "Read a file once with `grep -n` to locate, then one bounded `sed -n`/Read range; keep notes of what was learned "
        "instead of re-reading. After an edit, re-read only the edited range.", "none",
    )


def long_context(runs: list[Metrics]) -> Finding | None:
    long_runs = [run for run in runs if run["tokens"]["final_context"] >= LONG_CONTEXT]
    if not long_runs:
        return None
    value = lambda run: max(0, run["tokens"]["weighted"] - run["api_calls"] * SPLIT_CALL_WEIGHT - run["turns"]["onboarding_weighted"])  # noqa: E731
    return finding(
        "runs.long-context", f"Runs grow past {LONG_CONTEXT // 1000}k context tokens", sum(value(run) for run in long_runs), len(long_runs),
        "weighted cost above ~15k per call (a ~150k context) minus one extra onboarding, i.e. splitting each run once",
        [f"{len(long_runs)} runs; final contexts " + ", ".join(f"{run['tokens']['final_context']:,}" for run in long_runs), *top(long_runs, value)],
        "skills/spec-orchestrator/SKILL.md", "Loop (step 5) / Delegation prompts",
        "For specs with many requirements, delegate implementation in requirement batches to fresh implementers; "
        "the record carries state between them. Each batch hands back to the parent, then one reviewer covers all.", "none",
    )


def followups(runs: list[Metrics]) -> Finding | None:
    small = [run for run in runs if run["role"] in ("tester", "fixer", "implementer") and run["tool_calls"] <= 40]
    if not small:
        return None
    value = lambda run: int(run["turns"]["onboarding_weighted"] * 0.7)  # noqa: E731
    return finding(
        "runs.followup-onboarding", "Small follow-up rounds pay full onboarding", sum(value(run) for run in small), len(small),
        "onboarding cost (calls until the first edit/test/http/inspect action) x 0.7, saved by resuming the previous agent",
        [f"{len(small)} runs with <= 40 tool calls; onboarding " + ", ".join(f"{run['turns']['onboarding_weighted']:,}" for run in small[:6]), *top(small, value)],
        "skills/spec-orchestrator/SKILL.md", "Delegation prompts",
        "Allow a retest to resume the tester that found the bug (SendMessage) and a follow-up fix to resume the same fixer, "
        "instead of spawning fresh agents. Keep a fresh reviewer and a fresh tester for every first round.",
        "low: a resumed tester is still independent of the fixer; it may anchor on its own earlier reproduction, so require it to "
        "rerun the original reproduction steps",
    )


def bash_failures(runs: list[Metrics]) -> Finding | None:
    value = lambda run: run["bash"]["failures"] * run["turns"]["mean_call_weighted"] + run["bash"]["failure_carry"]  # noqa: E731
    count = sum(run["bash"]["failures"] for run in runs)
    if not count:
        return None
    by_role = roles_of(runs, value)
    codes: Counter = Counter()
    for run in runs:
        codes.update(run["bash"]["exit_codes"])
    retried = sum(run["bash"]["retried_after_failure"] for run in runs)
    return finding(
        "bash.failures", "Shell commands fail and are retried", sum(value(run) for run in runs), count,
        "one extra API call per failure (run's mean call cost) + context carry of the failure output",
        [f"{count} non-zero exits, {retried} identical retries", "exit codes: " + ", ".join(f"{code} x{n}" for code, n in sorted(codes.items())),
         "by role: " + ", ".join(f"{role} {value:,}" for role, value in by_role.most_common()), *top(runs, value)],
        ROLE_SKILL[main_role(by_role)], "2. Preparation",
        "Give agents the verified command prefix and a known-good invocation for build, test, and inspect commands in the "
        "delegation prompt; tell them to check `--help` once instead of guessing flags.", "none",
    )


def cli_errors(runs: list[Metrics]) -> Finding | None:
    classes: Counter = Counter()
    for run in runs:
        classes.update(run["cli_errors"])
    count = sum(classes.values())
    if not count:
        return None
    mean = sum(run["turns"]["mean_call_weighted"] for run in runs) // max(1, len(runs))
    worst = sorted(classes.items(), key=lambda item: (-item[1], item[0]))[0][0]
    return finding(
        "cli.rejections", "Workflow CLI calls are rejected", count * 2 * mean, count,
        "two API calls (the call and its correction) per rejected tracker or spec CLI call, at the mean call cost",
        ["by error class: " + ", ".join(f"{name} x{n}" for name, n in sorted(classes.items())),
         *top(runs, lambda run: sum(run["cli_errors"].values()))],
        "skills/spec-tracker/SKILL.md", CLI_SECTIONS.get(worst, "Commands"),
        "Put the exact next command for the current role in each delegation prompt, and document the failing class's rule "
        "beside its command in the tracker reference.", "none",
    )


def skill_loads(runs: list[Metrics]) -> Finding | None:
    value = lambda run: run["skills"]["carry"]  # noqa: E731
    total = sum(value(run) for run in runs)
    if not total:
        return None
    loads: Counter = Counter()
    sizes: dict[str, int] = {}
    for run in runs:
        for name, tokens in run["skills"]["loads"].items():
            loads[f"{run['role']}:{name.split(':')[-1]}"] += 1
            sizes[name.split(":")[-1]] = max(sizes.get(name.split(":")[-1], 0), tokens)
    return finding(
        "skills.load", "Skill text carried through every turn", int(total * 0.3), sum(loads.values()),
        "context carry of loaded skill bodies x 0.3 (trim or split into on-demand references)",
        ["skill sizes (tokens): " + ", ".join(f"{name} {size:,}" for name, size in sorted(sizes.items())),
         "loads by role: " + ", ".join(f"{name} x{n}" for name, n in sorted(loads.items())), *top(runs, value)],
        "agents/*.md and the largest skills", "skill bodies",
        "Move rarely needed detail (templates, catalogs, determinism rules) into references/ files loaded on demand, and load "
        "dev-inspection in the fixer only when the assigned bugs touch inspected state.", "none",
    )


def large_results(runs: list[Metrics]) -> Finding | None:
    items = [(run, item) for run in runs for item in run["large_results"]]
    if not items:
        return None
    value = sum(int(item["carry"] * (1 - LARGE_RESULT_CAP / item["tokens"])) for _, item in items)
    categories = Counter(item["category"] for _, item in items)
    worst = sorted(categories.items(), key=lambda pair: (-pair[1], pair[0]))[0][0]
    role = main_role(Counter(run["role"] for run, _ in items))
    if worst in ("read", "Read"):
        proposal = ("Read files in bounded ranges: `grep -n` to locate, then a Read with offset/limit or `sed -n a,bp` of about "
                    "100 lines; never `cat` a whole large file or print a whole JSON record.")
    else:
        proposal = (f"Pipe {worst} output through a filter (`| tail -n 40`, `grep -E 'FAIL|panic|Error'`, `--reporter=line`) and save "
                    "full logs to the scratchpad; read the log only when the summary shows a failure.")
    return finding(
        "context.large-results", "Large tool results stay in context", value, len(items),
        f"context carry of each large result above a {LARGE_RESULT_CAP:,}-token summary",
        ["by category: " + ", ".join(f"{name} x{n}" for name, n in sorted(categories.items())),
         *[f"{label(run)}: {item['tool']}/{item['category']} {item['tokens']:,} tokens" for run, item in sorted(items, key=lambda pair: -pair[1]["carry"])[:3]]],
        ROLE_SKILL[role], "3. Test methods" if role == "tester" else ("3. Implementation rules" if worst in ("read", "Read") else "4. Verification and handoff"),
        proposal, "none",
    )


def early_stops(runs: list[Metrics]) -> Finding | None:
    stopped = [run for run in runs if run["early_stop"]]
    if not stopped:
        return None
    return finding(
        "runs.early-stop", "Agents stop early (rate limit, crash, kill)", sum(run["turns"]["onboarding_weighted"] for run in stopped), len(stopped),
        "one onboarding per stopped run, saved by resuming the same agent instead of a fresh spawn",
        [f"{label(run)}: notifications {', '.join(run['notifications']) or 'none'}, api errors {run['api_errors'] or 'none'}" for run in stopped[:4]],
        "skills/spec-orchestrator/SKILL.md", "Resuming",
        "After a rate limit or stop, resume the same agent with SendMessage (it keeps its context) before spawning a fresh one.", "none",
    )


def bookkeeping(runs: list[Metrics]) -> Finding | None:
    only = [run for run in runs if run["bookkeeping_only"]]
    if not only:
        return None
    return finding(
        "runs.bookkeeping", "Agent runs that only update the tracker", int(sum(run["tokens"]["weighted"] for run in only) * 0.9), len(only),
        "weighted cost of the run x 0.9 (the parent light path costs a few calls)",
        [f"{label(run)}: {run['tokens']['weighted']:,}" for run in only[:4]],
        "skills/spec-orchestrator/SKILL.md", "Light path (trivial tracker bookkeeping)",
        "Use the parent light path for marking requirements from existing passed checks.", "none: the light path requires independent check evidence",
    )


def reports(main_runs: list[Metrics]) -> Finding | None:
    received = [run for run in main_runs if run["reports_received"]["count"]]
    count = sum(run["reports_received"]["count"] for run in received)
    tokens = sum(run["reports_received"]["tokens"] for run in received)
    if not count or tokens / count < 1500:
        return None
    later = sum(run["api_calls"] for run in received) // 2
    return finding(
        "parent.reports", "Long agent reports accumulate in the parent", int(tokens * 0.5 * (1.25 + 0.1 * later)), count,
        "half of the report tokens, carried for half of the parent's API calls",
        [f"{count} reports, {tokens:,} tokens, mean {tokens // count:,}"],
        "agents/*.md", "final message", "Cap agent final reports (e.g. 300 words); the record holds the details.", "none",
    )


def adhoc_tools(runs: list[Metrics]) -> Finding | None:
    value = lambda run: run["adhoc_scripts"]["carry"]  # noqa: E731
    count = sum(run["adhoc_scripts"]["count"] for run in runs)
    if not count:
        return None
    runs_per_name: Counter = Counter(name for run in runs for name in run["adhoc_scripts"]["names"])
    repeated = sorted(name for name, seen in runs_per_name.items() if seen > 1)
    by_role = roles_of(runs, value)
    return finding(
        "tools.adhoc", "Agents write throwaway test tools outside the project", int(sum(value(run) for run in runs) * 0.8), count,
        "output cost (x5) of writing each script outside the project plus its context carry, x0.8 (a registered tool is one short call)",
        [f"{count} scripts in {sum(1 for run in runs if run['adhoc_scripts']['count'])} runs, "
         f"{sum(run['adhoc_scripts']['tokens'] for run in runs):,} tokens",
         f"rebuilt in several runs: {', '.join(repeated) or 'none'}",
         "by role: " + ", ".join(f"{role} {value:,}" for role, value in by_role.most_common()), *top(runs, value)],
        "skills/test-toolkit/SKILL.md and " + ROLE_SKILL[main_role(by_role)], "Toolkit first / tool gaps",
        "Register each repeated script as a toolkit tool: the tester records `tool-gap add`, the toolsmith builds it in a "
        "toolkit location with a smoke test and `toolkit add`; later runs call it instead of rewriting it.",
        "none: the toolsmith builds tools; testers still plan from the spec and choose what to test",
    )


RULES = (batching, rereads, long_context, followups, bash_failures, skill_loads, large_results, early_stops, bookkeeping, adhoc_tools)


def build(runs: list[Metrics], limit: int) -> list[Finding]:
    agents = [run for run in runs if run["kind"] == "subagent"]
    found = [item for item in (rule(agents) for rule in RULES) if item]
    # CLI rejections and report sizes include the parent session.
    found.extend(item for item in (cli_errors(runs), reports([run for run in runs if run["kind"] == "main"])) if item)
    found.sort(key=lambda item: (-item["estimated_savings"], item["key"]))
    for rank, item in enumerate(found[:limit], 1):
        item["rank"] = rank
    return found[:limit]
