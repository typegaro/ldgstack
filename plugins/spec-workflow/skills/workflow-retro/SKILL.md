---
name: workflow-retro
description: Measure how the spec-workflow skills actually performed in a project, from Claude Code transcripts and tracker records, and rank token-efficiency and workflow improvements with evidence. Use when asked to evaluate skill performance, run a retro on a spec run, compare plugin versions, or after the spec-orchestrator queue empties.
---

# Workflow Retro

Data, not impressions. `scripts/retro.py` reads transcripts and records (read-only) and emits deterministic metrics plus ranked findings. Your job is to run it, sanity-check it, verify each finding against the current skill text, and report.

```bash
python3 <this skill's base directory>/scripts/retro.py --project <project root> \
  [--session <orchestrator session id> ...] [--since 2026-10-22T16:00] [--until ...] \
  [--label <plugin version>] [--compare <earlier retro.json>] [--top 10] [--large-tokens 5000] \
  [--conformance] [--model-weight sonnet=0.6 ...] --out-dir <dir> [--json]
```

Transcripts default to `~/.claude/projects/<project path with non-alphanumerics as ->/`: `<session>.jsonl` for main sessions and `<session>/subagents/agent-<id>.jsonl` (+ `.meta.json`) for agent runs.

## Steps

1. **Pick the input.** List the main session files with their modification times and whether they have a `subagents/` directory. Choose the orchestrator session(s) of the run with `--session`, or bound it with `--since/--until`. Exclude your own current session. Ask the user if the run is ambiguous.
2. **Run it** with `--out-dir` in your scratchpad, or `~/.claude/spec-workflow-retro/<project slug>/<label>/` if the user wants to compare versions later. `--label` is the plugin version (`.claude-plugin/plugin.json`).
3. **Sanity-check** before trusting it: runs per spec match the tracker history, `final_context` per run is close to the `subagent_tokens` in that agent's task notification, and tool-call counts match. Report any mismatch instead of hiding it.
4. **Verify each finding** against the current plugin: read the named skill file and section. Drop a finding the current text already addresses (say so), and sharpen the proposal to an exact edit.
5. **Report** the top 10 (see Output) to the user.
6. **Record**: append each new finding to `plugins/spec-workflow/ISSUES.md` (plugin source, not the cache) as an item headed with its key, e.g. `### N. <title> (retro: turns.batching)`. Skip keys that already appear; update their numbers instead when the user asks.
7. With `--compare`, report regressions and resolved findings between versions.

## Metrics

- **Tokens**: `processed` = input + cache write + cache read + output, summed over API calls (each message once, though Claude Code stores one line per content block). `weighted` = input + 1.25×cache write + 0.1×cache read + 5×output, a relative cost unit. `final_context` = the last call's context, which is what Claude Code reports as `subagent_tokens`. Never compare across these definitions.
- **Cost by model**: `by_model` and `cost units` = weighted × relative family price (opus 1.0, sonnet 0.6, haiku 0.2; `--model-weight FAMILY=W`); see [references/model-prices.md](references/model-prices.md). A `--since/--until` window also clips the main session. Plugin-development runs are reported apart, never as workflow cost: runs tagged `[plugin-dev]`, non-spec-role runs whose description names the plugin, spec-workflow, or ldgstack, and runs that write plugin source (`plugins/spec-workflow/` outside `~/.claude/plugins`). A run's spec comes from its `claim`, then the feature its tracker commands name most, the brief's `Feature:` line, the description's number, the prompt, then spec files it read; only `NNNN-<slug>` names of existing specs or records count as features. Runs belong to the window their start falls in, so disjoint `--since/--until` windows partition them; `--compare` refuses two reports that cover the same session over overlapping time unless `--force`.
- **Context carry**: a tool result of T tokens at API call p costs about T×1.25 + T×0.1×(calls after p). This is why a small read early in a 160-call run costs more than a large one at the end.
- **Turns**: tool calls per API call, read-only turns that directly follow another (batchable), onboarding (calls before the first edit, test, HTTP, or inspect action).
- **Time**: `active_seconds` (API call time + tool time per turn; idle gaps between resumes excluded) beside `wall_seconds`, and `bash_seconds` per test/build/lint/other; `tests.waiting` flags runs whose test+build time exceeds 40% of active time.
- **Friction**: non-zero Bash exits (classified: `pkill -f` self-match, missing toolchain prefix, zsh word split) and identical retries, re-reads of the same file, rejected tracker/spec CLI calls (classified by known message), early stops (API errors, non-completed notifications), resumed agents, bookkeeping-only runs.
- **Conformance** (`--conformance`): specs started before their dependencies were accepted, edits outside assigned paths or by read-only roles, first review/test rounds by a non-fresh agent, parent decisions without `--user-decision` (including direct spec edits), throwaway scripts rebuilt across rounds, delegation prompts not generated by `tracker brief`. Report each violated rule; never weaken the rule to clear it.
- **Ad hoc tools**: script files (`.py/.js/.cjs/.mjs/.ts/.sh/.go`) written outside the project (scratchpad, `/tmp`) by Write or shell redirects, per run, with normalized names (digits dropped) to show scripts rebuilt across runs (`tools.adhoc`). Recommend registering each as a toolkit tool (`test-toolkit`).
- **Effectiveness** (tracker records): bugs by finder role and severity, reopens, waivers, blockers, tool gaps (deferred), restores after acceptance.
- Tool-result sizes are estimated at 4 characters per token. Savings estimates overlap and rank changes; they are not additive.

## Output

For each of the top 10: title and key, estimated savings and frequency with the basis, evidence (spec, run ID prefix and description, numbers), the skill file and section to change, the exact proposed change, and its risk to review/test independence. Then the totals, by-spec and by-role tables, and the effectiveness summary.

## Rules

- Read-only: never modify the project, its records, or transcripts.
- Never paste transcript or tool-result content into the report or chat. Use only the script's sizes, names, counts, and redacted snippets. If you open a transcript to investigate, quote nothing from it.
- Never recommend removing independent review or testing, or weakening a gate. Propose a cheaper form instead (narrower scope, resumed agent, batched calls) and state the independence risk.
- A finding without numbers is an impression; leave it out or label it as a hypothesis.
