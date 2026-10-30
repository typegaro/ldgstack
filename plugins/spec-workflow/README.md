# spec-workflow

Specs in `specs/` are the immutable contract. The parent derives each spec's requirement list. A deep-reasoning planner writes a batched plan, an efficient execution model builds it batch by batch, an adversarial reviewer audits the code, an independent tester verifies real behavior, and a separate fixer fixes findings. The parent archives only through CLI-enforced gates.

Works in Claude Code and OpenCode (1.x and 2.x) from the same skills, scripts, and guard. Requires Python 3.10+.

## Install

### Claude Code

```text
/plugin marketplace add typegaro/ldgstack
/plugin install spec-workflow@ldgstack
```

Update with `/plugin marketplace update ldgstack`.

### OpenCode

Add the plugin to `opencode.json` (global `~/.config/opencode/opencode.json` or a project's):

```jsonc
// OpenCode 1.x
{ "plugin": ["spec-workflow@git+https://github.com/typegaro/ldgstack.git"] }
// OpenCode 2.x
{ "plugins": ["spec-workflow@git+https://github.com/typegaro/ldgstack.git"] }
```

Restart OpenCode. The plugin registers the skills, runs the path guard before file and shell tools, puts `spec` and `spec-tracker` on the shell `PATH`, and adds a short note that maps the Claude Code tool names in the skills to OpenCode's (`task`/`subagent`, `skill`, `question`).

On **1.x** the plugin also registers the six agents. On **2.x** plugins can't add agents yet, so link them once from a clone:

```bash
git clone https://github.com/typegaro/ldgstack.git
ldgstack/plugins/spec-workflow/opencode/install.sh                   # ~/.config/opencode/agents ($OPENCODE_CONFIG_DIR respected)
ldgstack/plugins/spec-workflow/opencode/install.sh --project <dir>   # or <dir>/.opencode/agents
```

For a local checkout instead of the Git URL, use its path: `"plugin": ["file://<clone>/plugins/spec-workflow/opencode/plugin.js"]` (1.x) or `"plugins": ["<clone>"]` (2.x).

Agents inherit your default model. Set the tiers per agent, e.g. `"agent": {"spec-planner": {"model": "<deep model>"}, "spec-reviewer": {"model": "<deep model>"}}` (1.x), or, on 2.x, install with `--copy` and add a `model:` line to the copied agent files.

## Contents

| Kind | Name | Purpose |
|---|---|---|
| Skill | `write-specs` | Scope-preserving spec writing, requirement format, append-only evolution, decision specs |
| Skill | `spec-cli` | `spec.py`: git for specs (new, list, ready, waves, defer, show --effective, log, graph, validate, archive, unlock, promote, adopt) |
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
| Hook | `guard_paths.py` | Blocks direct edits and shell writes to `implementation/{active,archive}/`, `spec-archive.json`, and `toolkit.json`; blocks creating spec files outside `spec.py new`; blocks edits to accepted specs unless unlocked; blocks subagent edits and shell writes to `specs/` (except `specs/.drafts/`) and subagent `spec.py new/archive/restore/unlock/relock/defer/undefer/promote/adopt` |
| Hook | `brief_check.py` | Advisory: warns when a spec-workflow Agent/Task prompt lacks the `tracker brief` marker |
| Bin | `spec`, `spec-tracker` | Wrappers for the two CLIs |
| OpenCode | `opencode/plugin.js` | 1.x and 2.x plugin: skills, agents (1.x), the same `guard_paths.py`, `PATH`, tool-name mapping |
| OpenCode | `opencode/agents/` | 2.x agents, generated from `agents/` by `opencode/build.py` |

## Project setup

```text
CLAUDE.md or AGENTS.md          # project root marker + project rules (verification commands, diagnostics CLI, test accounts)
specs/NNNN-<slug>.md            # every spec: feature | change | removal | convention | decision; created with `spec.py new`
                                # required: a convention spec for the developer inspection CLI
                                # recommended: a convention spec for pagination, errors, status codes, timeouts
implementation/preflight.json   # {"commands": [...]} every agent must be able to run
implementation/toolkit.json     # created by `spec-tracker toolkit add`; durable test tools (mocks, seeders, fe driver, ...)
```

Then ask the agent to "implement all specs" (`spec-orchestrator`) or to write a spec (`write-specs`).

## CLI entry points

`bin/spec` and `bin/spec-tracker` wrap `spec.py` and `spec_tracker.py`. To use them in your own shell, put the plugin's `bin/` on `PATH`:

```bash
export PATH="$HOME/.claude/plugins/cache/ldgstack/spec-workflow/<version>/bin:$PATH"   # Claude Code install
export PATH="<clone>/plugins/spec-workflow/bin:$PATH"                                   # a clone
```

Don't use `SPEC="python3 .../spec.py"; $SPEC validate`: zsh doesn't word-split `$SPEC`. Use the wrappers, a shell function, or the full command. Agents spell out the full command in each Bash call, since shell state doesn't persist between calls.

## Enforcement levels

- **Mechanical**: spec hashes, generation-scoped evidence, gates (current-generation reviewer + later tester checks required, `not_run` blocks acceptance), dependency-ordered `ready`/`next`, parent-only requirement list, bug lifecycle, serialized CLI state changes, role-gated mutations, handoff order (implementer → reviewer → tester; fixer → reviewer → tester; implementer → tester only for newly added requirements after a prior review), light-path evidence rules, tool gaps, read-only tool allowlists, path guards, archive requirements, and recorded user decisions. Spec synchronization reconciles changed and removed imported requirements and invalidates stale evidence.
- **Honor system**: `--parent-confirmed`, `--user-decision` content, and the record's `current_role` can be supplied or changed by any caller. The Bash guard catches redirections, `tee`, `cp`/`mv`/`rm`/`sed -i`-style writes, and the spec CLI, but not every way a script can write a file. The skills forbid all of this. Lane ownership fails open, with a warning, for an agent whose assignment is unknown (ambiguous role and no `claim`); hook input carries `agent_id`/`agent_type` but no prompt, so binding needs the brief's `claim` or a unique role. Whether the parent actually sends the brief verbatim is measured by `workflow-retro --conformance`, not enforced.

## Maintaining both platforms

The Claude Code plugin is the source. Edit `skills/`, `agents/`, and `hooks/` as usual; OpenCode reuses the skills and `guard_paths.py` as they are. After changing an agent or the version in `.claude-plugin/plugin.json`, run `python3 opencode/build.py`: it regenerates `opencode/agents/` and syncs the root `package.json` version. The tests fail while either is stale. Keep skill text in Claude Code terms; the plugin's mapping note translates them, so add a line to `mapping()` in `opencode/core.js` when a skill starts using a new Claude-only tool.

`workflow-retro` reads Claude Code transcripts only.

## Changes from the original OpenCode version

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

Planner/executor split, validated by a pilot project on 0033/0034: executor peak context fell from 250–550k (Opus implementers) to about 96–141k (Sonnet), review still caught real bugs, and all 5 executor questions were plan gaps the parent answered.

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

Rules that drifted as prose in a pilot run are now enforced in code (#20–#25):

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
- `requirement import [--exclude-amended]` derives the requirement list from `R<n>` bullets and (by default) cited older requirements.
- `not_run` blocks only acceptance. New `not_applicable` check result (non-blocking).
- `implementer → tester` after a passed review, for parent-added requirements only. The parent may `requirement add/import` and `blocker resolve` in any role with `--parent-confirmed`.
- Parent light path: `requirement implemented|tested --evidence-from <check>` and parent `check add`, shown as parent-attested.
- Hook covers Bash. Subagents may write proposals to `specs/.drafts/`; the parent applies them with `spec new --from` or `spec promote`.
- `gate <feature> <gate>` everywhere (old order deprecated), qualified blocker IDs (short form accepted), `archive` refuses specs without requirements, `bin/` wrappers.
- Additive record fields: `added_at`, `added_during_role`, `implemented_at`, `tested_at`, `parent_attested`, `resolved_during_role`, `handoff.review_skipped`; summaries gain `checks_not_run`, spec summaries gain `waiting_on`.

## Tests

```bash
python3 -m unittest discover -s tests     # includes the OpenCode plugin suite (node --test tests/opencode.test.mjs) when node is installed
```

Compatibility tests copy a real project with `specs/` and `implementation/` into a temp dir. Point `SPEC_WORKFLOW_COMPAT_ROOT` at one to run them; they are skipped otherwise.

## Changes in 0.7.1

Every feature spec ships its own testing and inspection plan, and its test tools are built with the feature (#36, #37, #38).

- write-specs: a `feature`/`change` spec with persisted or runtime state, a UI flow, or an external integration ends with `## Testability`: `- **R<n>** [ops]` requirements for Inspection, Drivers, Fault and mocks, Environment, and Verification. Template and example: `write-specs/references/testability.md`. Use `Not applicable: <reason>` for specs with none of these; decisions and docs are exempt.
- Reusable tools only: each Testability tool is a durable, generic command (subcommands, flags, JSON output, `--help`) that works for any future resource or scenario of the feature. It is registered in `toolkit.json` with a smoke test and maintained when the feature changes. One-off scripts, test procedures, and scenario-specific programs don't count; tests may call the tools. Review asks: "could a different tester reuse this tool for a new scenario without editing it?"
- `spec new` stamps an optional `workflow: <plugin version>` frontmatter key and a Testability skeleton. `spec validate` reports a missing or empty section as an error for specs stamped 0.7.1 or later (or every spec with `--strict-testability`), and as a warning for older specs. Accepted legacy specs are summarized in one line. Existing projects keep validating.
- adversarial-spec-review and spec-reviewer: a Testability check covers every new state, flow, and integration, every named failure path, and tool reusability.
- Planner: Testability requirements are ordinary executor batches (usually last), never toolsmith work. The toolsmith handles only gaps found later in review or testing (#36).
- Tracker: requirements imported from `## Testability` are flagged `testability`. Their `requirement implemented` evidence must name a registered toolkit tool whose smoke passed since its last change, plus its smoke check and `--help`; the record stores the tool. `tool-gap add --parent-confirmed` lets the parent record a gap in any role (#36 fallback), and a toolsmith check can back the parent light path. `brief --fresh` releases the role's assignment and issues a new one with the same paths (#37).

## Changes in 0.8.0

The orchestrator prioritizes parallel work (user request 2026-10-27; also resolves #43 and #48).

- `spec waves`: `startable` (= `ready`), `plannable` (draft specs whose unaccepted dependencies are all in progress or startable), topological levels, and `deferred`. `spec defer <id> --reason` / `undefer`: a derived `deferred` status in the manifest history; skipped by `ready`/`next`/`waves`, refused by `tracker init`, still linkable.
- `tracker init --early`: allowed without a user decision when every unaccepted dependency is in progress or startable. The record stores `early` and `blocked_on`; plans carry `**Requires:** <ids>|none` per batch; `assign --from-plan [--batch N]` and `brief --batch N` refuse batches whose required specs are unaccepted (no line = all of `blocked_on`; escape: `--parent-confirmed --user-decision`); `gate acceptance` and `archive` wait for `blocked_on`; `status` shows `blocked_on_pending`.
- `tracker overlap --plans`: pairs of active records whose planned ownership globs or active lanes may select the same files, checked before launching parallel executors.
- `init` leaves the record with the parent (status `new`); `handoff --to planner --parent-confirmed` also works while the executor has implemented nothing. Record schema stays v1; records written by 0.7.x keep working.
- Orchestrator: "Parallel scheduling" section (plan ahead, early batches, pipelined roles, concurrency cap, per-agent scratch dirs, serialized tracker writes). Planner: `Requires` on every batch, independent batches first.

## Changes in 0.8.4

From the 0.8.3 pilot retro (#44, #46, #51, #62–#65).

- `spec-sync` re-imports itself and invalidates only requirements whose text changed (amended targets follow their citing requirement) plus new ones; unchanged requirements keep marks and evidence. The plan is kept and marked `stale` (`status`, briefs); `brief --batch N` still works with a warning. `requirement import` includes amended targets by default (`--exclude-amended` opts out; `--include-amended` is a no-op).
- `brief` reissues a role's assignment that an earlier agent already claimed (same paths, stderr warning), so a fresh agent can always claim its brief.
- `assign` overlap errors list each overlapping pair, the narrowest existing non-overlapping globs, and a carve command; `assign --carve <glob> --from <ASSIGNMENT>` moves a narrow glob out of another spec's active lane (recorded on both, honored by the hook and the giving lane's brief). Planners own shared test infrastructure by file or narrow subdirectory.
- Briefs carry a `First turn:` line (one parallel read: spec, `requirement list`, the batch's files); agent prompts open their efficiency section with a batching rule. The orchestrator gives each plan batch (or 2 small ones) to a fresh executor.
- Tracker: `assign --role toolsmith --alongside` runs a toolsmith beside the active fixer on a disjoint lane; it ends with `tracker join`, and handoffs to review or test wait for it (#52).
- workflow-retro: plugin-dev runs detected by description and plugin-source writes; spec attribution from claims and tracker commands first, and only existing `NNNN-<slug>` features; windows partition runs by start time, and `--compare` refuses overlapping reports without `--force` (#61).
- workflow-retro: active time (API + tool time) beside wall time, Bash time per test/build/lint/other, a `tests.waiting` finding (test+build > 40% of active time), and exit-144 `pkill -f` / exit-127 missing-prefix and zsh word-split classes with fix hints.

## Changes in 0.9.0

OpenCode support from the same plugin; the separate OpenCode port is retired.

- `opencode/plugin.js`: one file for OpenCode 1.x (named export: config hook for skills and agents, `tool.execute.before`, `shell.env`, system-prompt note) and 2.x (`setup`: `skill.transform`, `tool`/`shell`/`session` hooks). The guard is the same `hooks/guard_paths.py`, fed Claude-shaped events; child sessions are subagents.
- `opencode/build.py` generates the 2.x agents from `agents/` and syncs the root `package.json` version; `opencode/install.sh` links them. Subagents can't nest (`task`/`subagent` denied); read-only roles can't edit.
- Root `package.json` and `index.js` make the repository installable as an OpenCode plugin from Git.
- Compatibility tests no longer default to a local project; set `SPEC_WORKFLOW_COMPAT_ROOT`.

## Changes in 0.10.0

Throughput from the 2026-10-30 retro (#76–#80): specs no longer share one working tree, testing runs one spec at a time, and small findings stop driving review rounds.

- **Worktree mode** (`implementation/workspace.json`): each code repo is a folder of checkouts, `<repo>/main` (accepted code) and `<repo>/<branch>` per spec. `tracker worktree create|status|merge|remove`; writer handoffs commit a checkpoint on the branch; reviewers diff `main...HEAD`; `worktree merge` checks every repo with `git merge-tree` and merges all or nothing after the acceptance gate; `archive` needs the merge and removes the checkouts. A dependent spec starts from its dependency's branch. Briefs gain a `Worktree:` line and run toolchain commands in the checkout; `spec preflight` runs them in `<repo>/main`. The guard denies subagent edits to `<repo>/main/` and compares lanes only inside one checkout, so specs no longer contend for files (`assign` reports `merge_risk` instead). Setup and adoption: orchestrator procedures › Worktree mode.
- **One test slot**: `test_slots` (default 1). `brief --role tester` refuses while another spec's tester is at work; implementation and review keep running in parallel.
- **Bigger, parallel batches**: planners aim for 3–5 batches and mark `**Parallel:** yes` for disjoint ones (e.g. be and fe); `assign --parallel` runs them as separate executors of one spec, and the last handoff waits until the others are released (`assign --release --assignment ID`).
- **Risk tiers and follow-ups**: `tracker risk <feature> high|normal` (briefs show `Risk:`). High keeps a fresh reviewer per fix round; normal resumes the finding reviewer on the fix diff. `bug follow-up` moves low bugs (medium with a user decision; never high or critical) out of the acceptance gate; `tracker follow-ups` lists them.
- Focused tests per batch; the tester runs the full suite once and tears its stack down before handing off.

## Changes in 0.10.1

- Worktree mode: `toolkit verify` runs smokes in `<repo>/main` (`--feature F` for that spec's checkouts), briefs show toolkit commands in the spec's checkout, and `toolkit add|update --location <repo>/...` accepts a path that exists in any checkout.
- `tracker abandon <feature> --reason --user-decision [--superseded-by ID]`: retire the record of a spec that is split or replaced before acceptance (kept in `implementation/abandoned/`, CLI-only); then `spec defer` it until the successor is accepted. Procedure: orchestrator procedures › Splitting or replacing an unaccepted spec.

## Changes in 0.10.2

- `assign --from-plan --batch N` claims only that batch's files: the paths under its `**Files:**` (else anywhere in the batch), backticks optional, `:line` dropped, kept only inside the plan's ownership; with none it falls back to the whole ownership and warns (#73). Disjoint batches can now run as `--parallel` executors without hand-written `--paths`.

## Changes in 0.10.3

- Parallel executors: an executor ends its batch with `tracker join <feature> --assignment <ID> --completed "..."` (its brief's Next command), releasing only its own lane; `handoff` is refused while sibling executor lanes are active, so one executor can no longer end another's lane mid-work.
- `brief --batch N` with several parallel lanes refuses when batch N has no lane of its own, instead of reissuing a sibling batch's lane (which released every lane and blocked the next `assign --parallel`).

## Changes in 0.10.4

- Fixes a 0.10.3 regression: sequential (non-parallel) batches end without a handoff again, so the next `brief --batch N+1` finds the lane; only executors with parallel siblings end with `join --assignment`.

## Changes in 0.10.5

- Worktree mode: commands that run inside one repo checkout and reach a sibling repo as `../<repo>` (e.g. `cd be && ... ../fe/tools/x.mjs`) now resolve to `../../<repo>/<branch>` when that repo has a checkout for the spec, else `../../<repo>/main`. Applies to briefs, `toolkit verify`, and `spec preflight`.
