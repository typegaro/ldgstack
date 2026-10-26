# spec-workflow

Specs in `specs/` are the immutable contract. The parent derives each spec's requirement list. A deep-reasoning planner writes a batched plan, an efficient execution model builds it batch by batch, an adversarial reviewer audits the code, an independent tester verifies real behavior, and a separate fixer fixes findings. The parent archives only through CLI-enforced gates.

## Contents

| Kind | Name | Purpose |
|---|---|---|
| Skill | `write-specs` | Scope-preserving spec writing, requirement format, append-only evolution, decision specs |
| Skill | `spec-cli` | `spec.py`: git for specs (new, list, ready, show --effective, log, graph, validate, archive, unlock, promote, adopt) |
| Skill | `adversarial-spec-review` | Contract-level review of specs |
| Skill | `spec-orchestrator` | Parent loop: implement → review → test → fix in dependency order |
| Skill | `test-toolkit` | Durable project test toolkit (`implementation/toolkit.json`): capability taxonomy, tool rules, tool gaps, frontend driver design |
| Skill | `dev-inspection` | Read-only, deterministic developer inspection CLI (the toolkit's `be.inspect` tool): spec template, invariant check catalog, lifecycle |
| Skill | `spec-tracker` | `spec_tracker.py` record CLI, gates, severity scale, blocker format |
| Skill | `workflow-retro` | `retro.py`: deterministic token/friction/effectiveness metrics from transcripts and records, ranked improvements |
| Skill | `spec-implementer` / `spec-reviewer` / `spec-tester` | Role rules |
| Agent | `spec-planner` (deep-reasoning tier) | Read-only planner: stores a batched plan with `tracker plan add` |
| Agent | `spec-implementer` (executor), `spec-fixer` (execution tier) | Code-editing roles |
| Agent | `spec-toolsmith` | Builds toolkit tools for recorded tool gaps; edits toolkit locations only |
| Agent | `spec-reviewer` (deep-reasoning tier), `spec-tester` (execution tier) | Read-only roles (no Edit/Write tools) |
| Hook | `guard_paths.py` | Blocks direct edits and shell writes to `implementation/{active,archive}/`, `spec-archive.json`, and `toolkit.json`; blocks creating spec files outside `spec.py new`; blocks edits to accepted specs unless unlocked; blocks subagent edits and shell writes to `specs/` (except `specs/.drafts/`) and subagent `spec.py new/archive/restore/unlock/relock/promote/adopt` |
| Hook | `brief_check.py` | Advisory: warns when a spec-workflow Agent/Task prompt lacks the `tracker brief` marker |
| Bin | `spec`, `spec-tracker` | Wrappers for the two CLIs |

## Project setup

```text
CLAUDE.md or AGENTS.md          # project root marker + project rules (verification commands, diagnostics CLI, test accounts)
specs/NNNN-<slug>.md            # every spec: feature | change | removal | convention | decision; created with `spec.py new`
                                # required: a convention spec for the developer inspection CLI
                                # recommended: a convention spec for pagination, errors, status codes, timeouts
implementation/preflight.json   # {"commands": [...]} every agent must be able to run
implementation/toolkit.json     # created by `spec-tracker toolkit add`; durable test tools (mocks, seeders, fe driver, ...)
```

Then ask Claude to "implement all specs" (`spec-orchestrator`) or to write a spec (`write-specs`).

## CLI entry points

`bin/spec` and `bin/spec-tracker` wrap `spec.py` and `spec_tracker.py`. To use them in your own shell:

```bash
export PATH="$HOME/.claude/plugins/cache/ldgstack/spec-workflow/<version>/bin:$PATH"   # or ~/Prj/ldgstack/plugins/spec-workflow/bin
```

Don't use `SPEC="python3 .../spec.py"; $SPEC validate`: zsh doesn't word-split `$SPEC`. Use the wrappers, a shell function, or the full command. Agents spell out the full command in each Bash call, since shell state doesn't persist between calls.

## Enforcement levels

- **Mechanical**: spec hashes, generation-scoped evidence, gates (current-generation reviewer + later tester checks required, `not_run` blocks acceptance), dependency-ordered `ready`/`next`, parent-only requirement list, bug lifecycle, serialized CLI state changes, role-gated mutations, handoff order (implementer → reviewer → tester; fixer → reviewer → tester; implementer → tester only for newly added requirements after a prior review), light-path evidence rules, tool gaps, read-only tool allowlists, path guards, archive requirements, and recorded user decisions. Spec synchronization reconciles changed and removed imported requirements and invalidates stale evidence.
- **Honor system**: `--parent-confirmed`, `--user-decision` content, and the record's `current_role` can be supplied or changed by any caller. The Bash guard catches redirections, `tee`, `cp`/`mv`/`rm`/`sed -i`-style writes, and the spec CLI, but not every way a script can write a file. The skills forbid all of this. Lane ownership fails open, with a warning, for an agent whose assignment is unknown (ambiguous role and no `claim`); hook input carries `agent_id`/`agent_type` but no prompt, so binding needs the brief's `claim` or a unique role. Whether the parent actually sends the brief verbatim is measured by `workflow-retro --conformance`, not enforced.

## Changes from the OpenCode version

- `code-structure` was removed; its project-relevant rules are folded into the implementer and reviewer skills.
- The parent derives requirements from the spec before implementation. The implementer can no longer write its own checklist.
- New per-spec `spec-reviewer` step (adversarial code review) between implementation and testing.
- The tester plans from the spec before seeing the implementation, using `requirement list`, which hides evidence. The parent never forwards implementer reports to verifiers.
- `not_run` checks fail both gates until waived. Waivers and not-a-bug closures require a recorded user decision. Acceptance requires passing reviewer and tester checks.
- Handoff transitions are enforced: a tester can't hand off to a fixer, and an implementer can't hand off to another implementer.
- Specs are append-only like migrations: tool-generated headers, links only to older specs, accepted specs frozen by the hook, history computed (`spec log/show --effective/graph`). Risks are `decision` specs; no unnumbered specs.
- `preflight` verifies the toolchain before delegating.
- Blockers are resolved, not deleted, and `spec-sync` keeps hash history.
- One severity scale (critical/high/medium/low), one blocker template (in `spec-tracker`).
- Root detection accepts `CLAUDE.md`, `AGENTS.md`, or `.git` (or `SPEC_WORKFLOW_ROOT`). Script paths are no longer hardcoded.
- Record schema is unchanged (v1). Existing records and `spec-archive.json` keep working.

## Changes in 0.7.0

Planner/executor split, validated by the m33 pilot on 0033/0034: executor peak context fell from 250–550k (Opus implementers) to about 96–141k (Sonnet), review still caught real bugs, and all 5 executor questions were plan gaps the parent answered.

- New role and agent `planner` (`spec-planner`, deep-reasoning tier, read-only). Plan template and mandatory checks (dependency trace, risks as steps, read-time fallbacks over rewrites, facts verified by command) in `spec-implementer/references/planning.md`.
- Tracker: `plan add <feature> --from FILE|-` (validates the template), `plan show [--batch N] [--version V]`, plans stored in the record; `assign --from-plan`; `brief --batch N` carries one plan batch plus the ownership. `handoff --to implementer` needs a plan for more than 3 requirements or more than one area, unless `--parent-confirmed --reason`.
- Questions: `handoff --to parent --question "..."` → `needs_answer`; `answer <feature> --text "..." [--replan]` routes back to the asker or to the planner. Answers show in briefs' `Decisions`. New statuses `planning`, `plan_ready`, `needs_answer`.
- Model tiers: planner and reviewer use the deep-reasoning tier; implementer, fixer, tester, and toolsmith use the efficient execution tier. Claude defaults are Opus and Sonnet respectively. Comparable OpenAI examples are GPT-5.6 Terra (`high`/`xhigh`) and GPT-5.6 Sol (`medium`/`high`); deployments should map tiers to available models rather than depend on these example names. The orchestrator documents escalation to the deep-reasoning tier.
- Retests: `check add` with the same name supersedes (the result reports `superseded`); tester and fixer briefs list failed and `not_run` checks by name; gate errors name the role that re-records each check and the handoff command. `handoff --to tester|planner` creates a read-only assignment when none is active.
- Batching (#9 follow-up): `brief --role implementer` refuses without `--batch` for more than 10 requirements, more than 2 areas, or a multi-batch plan, unless `--parent-confirmed`.
- Retro (#27, #29): feature regex ignores bug-ID suffixes and UUID chunks; `planner`/`toolsmith` roles; `--since/--until` clip the main session; `by_model` and `cost units` with relative model prices (`--model-weight`, `workflow-retro/references/model-prices.md`); `[plugin-dev]`-tagged runs reported apart; plugin versions read from tool inputs; per-spec requirement counts from records.
- Agents and briefs: "a read-only turn contains every read you already know you need"; spec-tracker's command block spells out every required flag; the advisory `brief_check.py` hook.
- Records without `plans`, `questions`, or planner assignments keep working (schema v1).

## Changes in 0.6.0

Rules that drifted as prose in the m33 run are now enforced in code (#20–#25):

- Lanes: `tracker assign <feature> --role <r> --paths <globs>|--read-only|--release --parent-confirmed`; `tracker claim <assignment>` (first command of a brief). The hook binds `agent_id` → assignment in `implementation/.assignments/` and denies subagent writes outside its paths or inside another active lane. Since 0.6.1 lane violations are advisory (warning + handoff note); set `SPEC_WORKFLOW_STRICT_LANES=1` to block.
- Dependency start guard: `init` and `handoff --to implementer` refuse specs whose `depends_on`/`amends` aren't accepted, unless `--parent-confirmed --user-decision`.
- Plugin cache: the hook denies Edit/Write and shell writes under `~/.claude/plugins/cache/` for everyone.
- `spec edit <id> --from <file> --reason [--user-decision] [--conflict]`: audited body replacement, logged in `spec log`; direct spec edits are denied for everyone; records show `pending` `spec-sync`/`requirement import` and gates wait for them. `promote` is a deprecated alias.
- `tracker brief <feature> --role <r> [--batch] [--final-batch]`: the full delegation prompt from `references/delegation-prompt.md`, filled from state.
- `retro.py --conformance`: early starts, edits outside lanes, non-fresh first verifier rounds, decisions without user decisions, reused throwaway scripts, prompts not from `brief`.
- CLI errors name the fix command. SKILL.md files stay under 120 lines and agents under 60 (tested); detail moved to `references/` (orchestrator procedures, tracker commands, review checklists).

## Changes in 0.5.0

- Durable test toolkit (#19): new `test-toolkit` skill (capabilities `be.inspect|seed|fault|concurrency`, `ext.mock.<service>`, `fe.drive|inspect|audit`, `env.isolate`, `data.cleanup`; tool rules; frontend driver design in `references/fe-driver.md`) and `spec-toolsmith` agent. `dev-inspection` is its `be.inspect` part.
- Tracker: `toolkit list|summary|add|update|verify|remove` over `implementation/toolkit.json`; `tool-gap add|resolve|defer|list`; new role and handoff target `toolsmith`; status `needs_tooling`/`tooling`; open gaps block the tester handoff and acceptance. Records without `tool_gaps` keep working.
- Roles: testers map requirements to capabilities and record gaps instead of writing throwaway scripts; reviewers flag missing capabilities and stale tools; implementers update affected tools and smoke tests; the orchestrator runs `toolkit verify` in preflight, dispatches the toolsmith, resumes the tester, and puts the toolkit summary in delegation prompts.
- `workflow-retro`: `tools.adhoc` metric and finding (scripts written outside the project, names rebuilt across runs); tool gap counts in effectiveness.
- #17 regression test: a tester's failed check doesn't block `ready-test` but blocks acceptance.

## Changes in 0.4.0

- Retro fixes #9–#16: batched implementers for large specs, a delegation-prompt template (`spec-orchestrator/references/delegation-prompt.md`) with known-good commands and the exact next command, parallel/bounded reads in agents and role skills, tester resume for retests and SendMessage resume after early stops, and dev-inspection's determinism and command catalogs moved to `references/` (fixers load it only when needed).

## Changes in 0.3.0

- New `workflow-retro` skill: `retro.py` measures runs from transcripts and tracker records (tokens, context carry, turn shape, friction, effectiveness) and ranks improvements mapped to skill sections. Read-only, deterministic, redacted.

## Changes in 0.2.0

- `spec ready` and dependency-ordered `next`: a spec is ready when its `depends_on` and `amends` targets are accepted. Independent specs may run concurrently; `tracker overlap` reports shared changed files.
- `requirement import [--include-amended]` derives the requirement list from `R<n>` bullets and cited older requirements.
- `not_run` blocks only acceptance. New `not_applicable` check result (non-blocking).
- `implementer → tester` after a passed review, for parent-added requirements only. The parent may `requirement add/import` and `blocker resolve` in any role with `--parent-confirmed`.
- Parent light path: `requirement implemented|tested --evidence-from <check>` and parent `check add`, shown as parent-attested.
- Hook covers Bash. Subagents may write proposals to `specs/.drafts/`; the parent applies them with `spec new --from` or `spec promote`.
- `gate <feature> <gate>` everywhere (old order deprecated), qualified blocker IDs (short form accepted), `archive` refuses specs without requirements, `bin/` wrappers.
- Additive record fields: `added_at`, `added_during_role`, `implemented_at`, `tested_at`, `parent_attested`, `resolved_during_role`, `handoff.review_skipped`; summaries gain `checks_not_run`, spec summaries gain `waiting_on`.

## Tests

```bash
nix-shell -p 'python3.withPackages(ps: [ps.pytest])' --run 'python3 -m pytest tests/ -q'   # or: python3 -m unittest discover -s tests
```

Compatibility tests copy `~/Prj/m33` (`SPEC_WORKFLOW_COMPAT_ROOT`) into a temp dir and skip if it is missing.
