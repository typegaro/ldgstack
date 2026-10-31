# spec-workflow: Known Issues

Observed while running the orchestrator on m33, specs 0021–0028, 2026-10-22/23.

## What worked (keep)

- Fresh reviewers and testers found real defects: a concurrent OAuth completion race, a misleading error code, and a wrong UI warning.
- Records survived a machine restart and an API rate-limit pause; work resumed from tracker state alone.
- Testers exercised real behavior: the live API, Playwright, mock servers, and the inspection CLI.
- Frozen specs turned conflicts (0004:R7 vs 0022) and risks (the Codex OAuth client) into recorded decisions.

## Issues

### 1. High cost per spec
**Resolved (0.2.0):** parent light path: `requirement implemented|tested --evidence-from <check> --parent-confirmed` and parent `check add`, shown as parent-attested; rules in spec-orchestrator.

0022 needed about 8 agent runs (~1.2M subagent tokens). Trivial follow-ups each need a full agent spawn: marking one requirement tested, re-recording one lint check.
- **Fix:** add a "light" path. The parent may run a narrow tracker-only step, such as re-recording a check or marking one requirement with existing evidence, under a gate that still requires independent evidence.

### 2. Strict numeric ordering blocks independent work
**Resolved (0.2.0):** `spec ready`; `next` = lowest ready spec (all `depends_on`/`amends` accepted). Concurrency rules plus `tracker overlap` in spec-orchestrator.

"Never start a later spec while an earlier one is active" held frontend specs 0023–0026 behind OAuth spec 0022, which they don't depend on. The user saw no UI change for hours.
- **Fix:** order by the `depends_on` graph. Allow independent specs to run in parallel, or let the user set the priority order (`spec.py next --respect-deps`).

### 3. Tracker role transitions are too rigid
**Resolved (0.2.0):** `implementer → tester` after a passed review for requirements added since; `not_run` blocks only acceptance; `requirement add/import` and `blocker resolve` in any role with `--parent-confirmed`.

- An implementer cannot hand off to a tester; only the reviewer or parent can. That adds an extra round-trip.
- A `not_run` check blocks even a narrow bug retest handoff. The waiver must come before the retest, although the retest doesn't depend on it.
- The parent must first `handoff --to parent` before `blocker resolve` when the record is in a fixer or implementer role.
- Requirements the parent adds after implementation (spec amendments) block tester handoff until a full implementer run marks them.
- **Fix:** allow `implementer → tester` when the gate passes. Scope `not_run` checks to acceptance rather than retest. Let the parent resolve blockers in any role.

### 4. The subagent hook is bypassable
**Resolved (0.2.0):** the hook matches Bash. It denies subagent spec-mutating `spec.py` commands and shell writes into `specs/`, and denies shell writes into state for everyone. Subagents may write `specs/.drafts/`; the parent runs `spec new --from` or `spec promote`.

The hook blocks Edit/Write on `specs/` for subagents, but `spec.py new` through Bash still created files. The result was empty skeletons 0021–0026 committed by a subagent.
- **Fix:** either block `spec.py new/archive/restore` in subagents too, or officially let subagents produce drafts in a staging dir (e.g. `specs/.drafts/`) that the parent promotes.

### 5. `inspect check all` is assumed but optional
**Resolved (0.2.0):** the dev-inspection convention requires `check all`. Where it's missing, skills record a `not_applicable` check (new, non-blocking result).

The orchestrator and testers expect an inspection `check all` command. m33's CLI has none, so every agent reported it as not applicable.
- **Fix:** make the dev-inspection convention require `check all` explicitly, or have the skills detect it and skip cleanly.

### 6. Requirement derivation is manual
**Resolved (0.2.0):** `requirement import <feature> [--include-amended]`, idempotent by spec ref.

The parent had to script parsing of `- **R<n>**` lines, including multi-line bullets, into `requirement add` calls.
- **Fix:** add `spec_tracker.py requirement import <feature> [--amended]`. It parses R-lines from the effective spec, uses the requirement text as the default verification, and optionally pulls in the touched requirements of amended specs.

### 7. CLI papercuts
**Resolved (0.2.0):** `gate <feature> <gate>` (old order deprecated), `BLOCKER-<feature>-NNN` (short form accepted), `archive` refuses specs without `R<n>` bullets, `bin/spec` and `bin/spec-tracker`, and zsh-safe docs. The docs say archive rechecks gates.

- `gate` takes `<gate> <feature>`, while other commands take the feature last. Use one order everywhere.
- Blocker IDs are short (`BLOCKER-001`), bug IDs are fully qualified (`BUG-<feature>-001`). Make them consistent.
- `spec.py archive` accepted a `decision` spec with an empty body. Reject archive when the body has no requirements.
- `spec.py` and `spec_tracker.py` live only in the plugin cache path. Offer an installable entry point (`spec`, `spec-tracker`) so prompts don't carry long absolute paths. Under zsh a `$VAR` command prefix does not word-split.
- After a failed gate, `archive` still runs in a chained shell command. `archive` itself rechecks the gate, which is good, but the docs should state it.

### 8. Implementation records hold uncommitted spec edits
**Resolved (0.2.0):** write-specs and spec-orchestrator document draft edits: allowed before acceptance, then `spec-sync`, `requirement import`, and back to the implementer if requirements changed.

The parent amended draft spec 0022, which had already started, then had to run `spec-sync`. The workflow for "a draft spec changed after its record was created" is underspecified.
- **Fix:** document when a draft may change (before acceptance) versus when a new amending spec is required.

## Priority

1. Dependency-based ordering (#2)
2. `requirement import` (#6)
3. A light path for trivial follow-ups (#1) and relaxed role transitions (#3)

## Retro findings (workflow-retro on m33 session b43fa2d7, plugin 0.1.0, specs 0021–0024)

Weighted tokens = input + 1.25×cache write + 0.1×cache read + 5×output. 20 agent runs: 169M processed, 25M weighted, 2.9M final context (Claude Code's `subagent_tokens`). Estimates overlap.

### 9. Implementer runs grow past 250k context (retro: runs.long-context)
**Resolved (0.4.0):** spec-orchestrator delegates large specs to fresh implementers in requirement batches; the record carries state; one reviewer covers all.
Three implementer runs ended at 330k–421k context. Every late call re-reads it, at 27k–39k weighted per call. Estimated 7.6M weighted saved by splitting each run once.
- **Fix:** spec-orchestrator delegates large specs to fresh implementers in requirement batches; the record carries state; one reviewer covers all.

### 10. Read-only turns are not batched (retro: turns.batching)
**Resolved (0.4.0):** agent prompts, role skills, and the delegation template batch independent reads, greps, and status commands into one turn.
1.05 tool calls per API call; 273 read-only turns directly followed another, implementer 61% of them. Est. 5.1M.
- **Fix:** agent prompts and role skills: issue independent reads, greps, and status commands as parallel calls in one turn.

### 11. Shell command failures (retro: bash.failures)
**Resolved (0.4.0):** the delegation template carries known-good build/test/inspect commands; agents check `--help` once.
43 non-zero exits (1 ×30, 144 ×8, 127 ×3), mostly implementer and tester. Est. 0.97M.
- **Fix:** delegation prompts include known-good build/test/inspect invocations; agents check `--help` once.

### 12. Large file reads and re-reads (retro: context.large-results, context.rereads)
**Resolved (0.4.0):** spec-implementer "Implementation rules": `grep -n`, then one bounded range; re-read only edited ranges.
17 results ≥5k tokens, all file reads (Bash `cat`/`sed` or Read). 119 re-reads of an already-read file, implementer 72%. Est. 0.65M + 0.56M.
- **Fix:** spec-implementer "Implementation rules": `grep -n` to locate, then one bounded range; after an edit, re-read only the edited range.

### 13. Small follow-up rounds pay full onboarding (retro: runs.followup-onboarding)
**Resolved (0.4.0):** a retest may resume the tester that found the bugs via SendMessage; first review and test rounds stay fresh.
Six runs with ≤40 tool calls (single-bug fix and retest, finish R16a, mark REQ-030) each paid 46k–153k weighted in onboarding. Est. 0.31M.
- **Fix (policy change, user decision):** a retest may resume the tester that found the bug via SendMessage, rerunning the original reproduction. First review and test rounds stay fresh.

### 14. Early stops restart from scratch (retro: runs.early-stop)
**Resolved (0.4.0):** spec-orchestrator "Resuming": resume a stopped agent with SendMessage before spawning a new one.
Test 0022 hit a rate limit; Implement 0024 was stopped. Est. 0.19M.
- **Fix:** spec-orchestrator "Resuming": resume the same agent with SendMessage before spawning a new one.

### 15. Skill text carried through every turn (retro: skills.load)
**Resolved (0.4.0):** dev-inspection's determinism contract and command catalog moved to references/; fixers load dev-inspection only when their bugs touch inspected state.
46 skill loads, dev-inspection the largest (2.8k tokens), loaded by every implementer and fixer. Est. 0.17M.
- **Fix:** move the determinism contract and catalogs to references/; fixers load dev-inspection only when their bugs touch inspected state.

### 16. Rejected workflow CLI calls (retro: cli.rejections)
**Resolved (0.4.0):** the delegation template carries the exact next tracker command.
Five rejected calls: role ×1 (addressed by 0.2.0's relaxed transitions) and usage ×4, four of them in the parent.
- **Fix:** delegation prompts carry the exact next command; re-measure on 0.2.0.

Effectiveness: reviewers recorded 10 of the 11 bugs in 0021–0024 and testers 1; there was one reopen. Keep both steps; this run's defects came almost entirely from review.

### 17. Tester's failed check deadlocks the retest handoff
After the fixer fixes the bugs, the tester's own `failed` check blocks the `ready-test` gate. Only the tester can re-record that check, but the tester can't get the record back.
**Resolved (0.5.0):** `gate_errors` ignores tester-owned failed checks for every gate except `acceptance`. Regression test: `tests/test_toolkit.py::ToolGapTest::test_tester_failed_check_blocks_acceptance_not_retest_handoff`.

### 18. Parallel lanes exhaust the API session limit together
Three heavy lanes (0024, 0028, 0029) running at once hit the account's session limit, and all three stopped at the same time.
**Resolved (0.6.0):** spec-orchestrator "Concurrency": at most 2 heavy lanes, staggered starts.
- **Fix:** spec-orchestrator recommends at most 2 concurrent heavy lanes and staggers implementer starts.

### 19. Testers rebuild throwaway tools each round (retro: tools.adhoc)
**Resolved (0.5.0):** `test-toolkit` skill, `spec-toolsmith` agent, `tracker toolkit` manifest with smoke tests, and `tracker tool-gap` (blocks tester handoff and acceptance until resolved or deferred by the user). Testers record gaps instead of writing scripts; the orchestrator verifies the toolkit in preflight.
Testers wrote a mock OAuth server and ChatGPT backend, a mock MCP server, Playwright drivers and screenshotters, `go -overlay` programs to plant DB state or read credentials, private fe copies with port rewrites (`lane24/sync.sh`), and seed and cleanup scripts in the session scratchpad, and rebuilt them each round. Retro on session b43fa2d7: 58 scripts outside the project in 7 runs (tester 45, implementer 10), ~57k tokens of script text, ~0.5M weighted; `mock.py`, `s*.py`, `lib.py`, `insp.sh` rebuilt across runs.
- **Fix:** a durable, project-owned toolkit registered in a CLI-managed manifest, filled through recorded tool gaps by a toolsmith, and maintained by implementers as features change.

## Prose-only rules drifted (m33 run, plugin 0.4.0–0.5.0)

The CLI- and hook-enforced rules held; rules stated only in skill text drifted. 0.6.0 moves them into code and measures the rest with `workflow-retro --conformance`.

### 20. Specs started before their dependencies were accepted (conformance: deps.early-start)
0026 (depends on 0018/0023, amends 0025) was implemented while 0025 was still active.
**Resolved (0.6.0):** `tracker init` and `handoff --to implementer` refuse it unless `--parent-confirmed --user-decision`; the override is stored and shown in briefs.

### 21. Lane ownership violated (conformance: lanes.outside)
Concurrent agents edited files owned by another spec's lane; ownership lived only in prompt text.
**Resolved (0.6.0):** `tracker assign` stores per-agent globs; the hook binds the agent (`claim`, or a unique role) and denies writes outside its lane or inside another. Unknown assignments fail open with a warning.

### 22. Parent hot-patched the plugin cache
Fixes were applied to `~/.claude/plugins/cache/...`, diverging from the source and lost on update.
**Resolved (0.6.0):** the hook denies cache writes for everyone; releases go through source, version bump, `claude plugin update`.

### 23. Parent edited draft specs and decided conflicts without the user (conformance: decisions.no-user)
In-place edits left no audit trail; conflicts (e.g. 0004:R7 vs 0022) were sometimes settled by the parent alone. Empty skeletons were committed.
**Resolved (0.6.0):** direct spec edits are denied for everyone; `spec edit --reason` is logged in `spec log`, needs `--user-decision` for in-progress specs and `--conflict` resolutions, and marks the record's `spec-sync`/`requirement import` as pending (gates wait). Skeletons stay unacceptable (`archive` refuses specs without requirements).

### 24. Hand-written delegation prompts carried uneven rules (conformance: prompts.not-brief)
Efficiency rules, toolchain lines, and next commands varied between prompts.
**Resolved (0.6.0):** `tracker brief` renders the template from durable state; the orchestrator sends it verbatim. Skills have a tested length budget; detail lives in `references/` and CLI error messages, which name the fix command.

### 25. No measurement of workflow conformance
Rule drift was found by reading transcripts.
**Resolved (0.6.0):** `retro.py --conformance` reports six rule checks; on session b43fa2d7 it flags 0026's early start, 29 hand-written prompts, and 4 throwaway scripts rebuilt across runs.

### 26. Lane ownership blocking is too strict
The user found hard path blocking too restrictive for subagents.
**Resolved (0.6.1):** lane violations are advisory by default. The hook warns and asks the agent to mention the edit in its handoff. `SPEC_WORKFLOW_STRICT_LANES=1` restores blocking. The retro conformance check still reports out-of-lane edits.

## Retro findings (workflow-retro on m33 session b43fa2d7, plugin 0.4.0–0.6.1, specs 0024–0032, 2026-10-23/25)

33 agent runs, 41.2M weighted (2 plugin-dev runs: 2.9M). Existing keys recur (runs.long-context 9.6M, turns.batching 9.5M, cli.rejections 5→20, prompts.not-brief 8 of 14 delegations after 0.6.0); see `~/.claude/spec-workflow-retro/m33/0.6.1/retro.md`.

### 27. Verifier freshness check misreads IDs as specs (conformance: verifiers.non-fresh)
**Resolved (0.7.0):** `TRACKER_FEATURE = \b([0-9]{4}(?:-[a-z][a-z0-9]*)+)\b`; regression test with a bug ID and a session UUID.
All 5 violations are false positives: `TRACKER_FEATURE` in `retrolib/transcripts.py` matches bug-ID suffixes (`<feature>-002`) and session-UUID chunks as features, so single-spec retests look like multi-spec runs.
- **Fix:** `TRACKER_FEATURE = re.compile(r"\b([0-9]{4}(?:-[a-z][a-z0-9]*)+)\b")` (every slug segment starts with a letter); add a regression test with a bug ID and a UUID.

### 28. Playwright driver rebuilt across tester runs (conformance: tools.reused-throwaway)
**Resolved (0.7.0):** spec-tester "Toolkit first": a UI requirement without `fe.drive`/`fe.inspect` gets its gap before the first browser probe.
`p.mjs` written by the 0025 and 0031 testers (24 ad hoc scripts in 0.6.1-era runs) before `fe-drive` was registered for 0026. Testers after the toolkit existed wrote 0.
- **Fix:** spec-tester "Toolkit first": when `toolkit list` lacks `fe.drive`/`fe.inspect` and a requirement is UI, record the gap before the first browser probe instead of after.

### 29. Retro metrics misattribute runs (retro: script.accuracy)
**Resolved (0.7.0):** main session clipped to the window; `spec-toolsmith`/`spec-planner` roles; `[plugin-dev]`-tagged runs reported apart; versions from tool inputs; requirement counts from records; cost by model with relative prices.
- `--since` drops whole runs but does not clip the main session: parent totals cover 2026-10-22 onward (wall 226k s); bounded estimate is ~8.2M weighted, not 11.1M.
- `SPEC_ROLES` lacks `spec-toolsmith`, so toolsmith runs are `other` and skip the brief check.
- General-purpose plugin-dev runs in the orchestrator session (2.9M, 9 scripts, 4 CLI rejections) count as workflow cost.
- `plugin_versions` is empty for every run; requirement counts differ from the records (0025: 20 vs 23, 0028: 10 vs 13, 0031: 3 vs 5).
- **Fix:** clip main-session calls to the window; add `"spec-toolsmith": "toolsmith"`; exclude runs with no spec and no tracker call from role tables (report them separately); read versions from skill-load paths (`/spec-workflow/<v>/` appears in tool inputs); count requirements from the record.

### 30. Final gate found 12 defects after per-spec acceptance (retro: effectiveness.final-gate)
**Resolved (0.7.0):** procedures Completion step 5: each finding names the spec it escaped from and the finder class.
The whole-codebase review and cross-spec test (2 runs, ~0.9M weighted) produced spec 0032 (R1–R12): 1 escape from 0026 (pagination cursor), 6 in older specs (0002, 0003, 0007, 0019, 0022), lint, and 4 toolkit gaps. Per-spec rounds this run: reviewer 17 bugs, tester 13.
- **Fix:** spec-orchestrator `references/procedures.md` "When the queue is empty": keep the gate; add that its findings name the originating spec and finder class, so the retro can attribute escapes.

## Pilot findings (planner/executor split on m33 specs 0033/0034, plugin 0.6.1, 2026-10-25)

Opus planner → Sonnet executor/fixer/tester/toolsmith → Opus reviewer. Executor peak context 96–141k (Opus implementers: 250–550k); reviewers rated the code good and close to the plan and still caught real bugs.

### 31. Implementers run on Opus at 250–550k context
**Resolved (0.7.0):** `spec-planner` (opus) writes a batched plan; executors, fixers, testers, and toolsmiths run on sonnet via agent frontmatter; `plan add|show`, `assign --from-plan`, `brief --batch N`; a plan is required for more than 3 requirements or more than one area.

### 32. Executor questions come from plan gaps
All 5: missed files (icons file, migration version constant, loader/claim code for a fallback), a known risk as a note (tool count after reload), a backfill rewriting immutable snapshots, a wrong weekday.
**Resolved (0.7.0):** mandatory planner checks in `references/planning.md` (dependency trace, risks as steps, read-time fallbacks, facts by command); `handoff --to parent --question` / `answer [--replan]` route questions without another planner round.

### 33. Retests re-record checks under new names, then hit a parent-attestation dead end
**Resolved (0.7.0):** same-name `check add` supersedes (reported); retest and fixer briefs list failed and `not_run` checks by exact name; gate errors name the role and the handoff command that re-records each blocking check.

### 34. Tester briefs fail without a tester assignment
**Resolved (0.7.0):** `handoff --to tester` (and `--to planner`) creates a read-only assignment when none is active.

### 35. Briefs sent as pointers (0.6.1 retro: prompts.not-brief)
Some delegations said "run brief ..." instead of pasting it.
**Resolved (0.7.0):** orchestrator rule plus the advisory `brief_check.py` PreToolUse hook on Agent/Task prompts for spec-workflow subagents.

### 36. Toolkit requirements deadlock the toolsmith route
**Resolved (0.7.1):** Testability requirements are planned as executor batches, never toolsmith work (`planning.md`, `spec-planner`). Fallback: `tool-gap add --parent-confirmed` in any role, and a toolsmith's passed check can back `requirement implemented --evidence-from ... --parent-confirmed`.
When a spec requirement is itself a toolkit tool (0036:R42 compute-fault), the planner assigns it to the toolsmith. The parent can't record a tool gap (only reviewer or tester can), the toolsmith handoff needs an open gap, and the reviewer handoff needs every requirement implemented. The parent had to route it to an implementer instead.
- **Fix:** let the parent run `tool-gap add --parent-confirmed`, or let the planner mark requirements `toolsmith`-owned so `handoff --to toolsmith` accepts them.

### 37. Fresh executor per batch requires a manual re-assign
**Resolved (0.7.1):** `brief --batch N --fresh` releases the active assignment and issues a new one with the same paths.
Moving a batch to a fresh agent (to keep context small) fails the `claim`, because the previous executor holds the assignment. The parent has to `assign --release`, then `assign --from-plan`.
- **Fix:** `brief --batch N --fresh` (or a new batch) issues a new assignment automatically.

## User requirement (0.7.1)

### 38. Specs ship without a testing and inspection plan
Test tools arrived late, through tool gaps, after the feature was built (the source of #36). The user requires every new spec to carry its own testing and inspection plan, with the inspection CLI and test tools built as normal requirements of the same spec. Each tool must be reusable: a durable, generic command (subcommands, flags, JSON output, `--help`) that works for any future scenario, is registered in the toolkit with a smoke test, and is maintained with the feature. One-off scripts and test procedures don't count. Review asks: "could a different tester reuse this tool for a new scenario without editing it?"
**Resolved (0.7.1):** `## Testability` section with a template (write-specs); `spec validate` reports a missing section as an error for specs stamped `workflow: 0.7.1`+ and as a warning for older ones (`--strict-testability` for all); review checks coverage and reusability; the tracker requires a verified toolkit tool, its smoke check, and `--help` in Testability evidence.

### 39. Failed checks owned by a role other than tester deadlock the handoff
A reviewer-owned failed check blocked the handoff back to the reviewer, the only role that can re-record it. Same class as #17.
**Resolved (0.7.2):** `ready-test` exempts failed checks owned by the target role (as well as the tester); acceptance still requires them all to pass.

### 40. Test-only fixes invalidate every requirement's tested status
In 0036, generations 11–16 were fixes to test helpers only (lint, the testdb helper). Each fixer revision bumped the generation and cleared `tested` on all 43 requirements, so a full retest-marking pass was needed before acceptance.
- **Fix:** when a fix round changes only test files (`*_test.go`, test helpers, toolkit tools), keep `tested` on requirements whose implementation files are untouched. Invalidate only the requirements whose recorded implementation paths overlap the changed files.

### 41. A parent question blocks the executor from recording finished work
In 0038 batch 7 the executor asked the parent a question (an environment blocker: dev Postgres was down after a reboot), then the parent fixed the environment and told it by SendMessage to continue. The executor finished all its work, but `check add`, `requirement implemented` and `handoff` refused because the record was still with the parent. It needed an extra `tr answer` round trip.
- **Fix:** when an agent asks an environment-only question, let the parent answer from the same message that resumes the agent, or have `brief`/the resume hint remind the parent to run `answer` first. Alternatively allow `check add` from the asking role while the question is open (it doesn't change ownership).

### 42. brief_check hook flags pointer-style briefs
The PreToolUse hook warns when the prompt lacks the `[Generated by spec-tracker brief` marker. Sending `cat <brief-file>` instead of pasting 12–18 KB verbatim saves parent context on every launch, and the executor still reads the exact brief.
- **Fix:** accept a prompt that names a brief file whose first line contains the marker.

### 43. No way to defer or withdraw a draft spec
The m33 user deferred 0043 (Kubernetes adapter) until the product is ready. spec-cli has no delete, withdraw or defer command, and deleting the file would break accepted decision 0044's `references`. `ready`/`next` will keep offering it.
- **Fix:** add `spec defer <id> --reason` / `spec undefer <id>` (a derived `deferred` status logged in history, excluded from `ready`/`next`, still valid as a link target). Optionally `spec withdraw` for drafts nobody references.
**Resolved (0.8.0):** `spec defer <id> --reason` / `spec undefer <id>` (derived `deferred` status in the manifest history, skipped by `ready`/`next`/`waves`, `list` shows `[deferred]`, still a valid link target). `spec withdraw` was not added.
- Also: `assign --from-plan` reported "no plan stored" for 0038 after several fix rounds although the plan existed earlier (fixer reassignment); used `--paths` as a workaround.

### 44. spec-sync resets every requirement after a one-line spec edit
In 0038, amending only R24 (adding one error code) with `spec edit` + `tracker spec-sync` invalidated implemented and tested on all 37 requirements. The fixer then could not hand off (it can't re-mark them), and the parent had to re-mark all 37 by hand with `--evidence-from`.
- **Fix:** spec-sync should diff the effective requirement text and invalidate only requirements whose text changed (plus newly added ones). Also allow `requirement implemented --evidence-from` in bulk (`--all-unchanged`).

**Resolved (0.8.4):** spec-sync re-imports and invalidates only requirements whose text changed (amended targets follow their citing requirement) plus new ones; unchanged ones keep marks and evidence, so no bulk re-mark is needed.

### 45. Resumed testers lose `claim`, and agents share one scratchpad
In the 0038 retest the resumed tester's `claim` failed ("unknown or released assignment") after the parent re-assigned the tester role (a new assignment ID), although tracker writes still worked. Another agent also overwrote the tester's helper script in the shared session scratchpad.
- **Fix:** `brief`/assign should print the active assignment ID so a resumed agent can re-claim it, or `claim` should accept the role. The skill should tell each agent to use a per-agent subdirectory (`$SCRATCH/<role>-<assignment>/`).

### 46. Claims held by agents that died at the usage limit block new agents
In 0039 a fixer from another session stopped at the usage limit while holding the claim on ASSIGN-022. The new fixer's `claim` was refused ("already claimed by another agent") and the hook would block its writes, wasting one launch. The parent had to issue `brief --fresh`.
- **Fix:** when the parent launches a new agent for a role whose assignment is claimed, `brief` should warn and offer `--fresh` automatically, or claims should expire (heartbeat on tracker writes, e.g. 30 min idle) so a parent-confirmed reclaim is allowed.

**Resolved (0.8.4):** `brief` reissues a claimed assignment (same paths, new ID, stderr warning), so a new agent can always claim its brief.

### 47. Testers skip marking passing requirements when they find bugs
In 0039 the tester exercised most areas successfully but marked no requirement tested and verified no bug, because new bugs were found. The next round must redo or re-cite all of it.
- **Fix:** the tester skill should mark tested/verify everything that passed in the current generation before handing back with bugs; with #40 those marks survive fixes that don't touch their files.
- Also: `brief --fresh` after `handoff --to fixer` fails with "no fixer assignment to renew"; it should create one from the previous fixer assignment's paths.

### 48. `init` puts a new record straight into implementing, skipping the planner
`tracker init` + `requirement import` left 0040 in `implementing (implementer)`. The orchestrator step "handoff --to planner" then failed ("implementer cannot hand off to planner"), even with `--parent-confirmed`. Workaround: `handoff --to parent --question ...` then `answer --replan`.
- **Fix:** `init` should leave the record with the parent (or in `planning` when the spec has more than 3 requirements), and the parent should be able to `handoff --to planner --parent-confirmed` from any pre-implementation state.

**Resolved (0.8.0):** `init` leaves the record with the parent (status `new`); `handoff --to planner --parent-confirmed` works from `new`, `plan_ready`, and an implementer that has implemented nothing. Existing records are unchanged (schema v1).

### 49. Orchestrator runs specs one at a time (user request, 2026-10-27)
Independent specs, and specs whose dependencies are still in review or test, wait idle although planning and some batches could proceed.
**Resolved (0.8.0):** `spec waves` (startable, plannable, levels, deferred); `tracker init --early` with per-batch `**Requires:**` gating and an acceptance block until `blocked_on` specs are accepted; `tracker overlap --plans` for lane conflicts; the orchestrator's "Parallel scheduling" section (plan ahead, pipelined roles, concurrency cap of 2 executors/fixers plus 1 deep-tier agent, resume after usage-limit stops, per-agent scratch dirs, serialized tracker writes).

### 50. `assign --from-plan` for fixers fails after a fix round ("no plan stored")
Plans are tied to the record generation, and every fix round bumps it, so `assign --role fixer --from-plan` failed on 0038, 0039 and 0040.
**Resolved (0.8.1):** fixer and toolsmith assignments use the newest plan's ownership regardless of generation; executor batches still require a plan for the current generation.

### 51. Finished writers keep their file lane, blocking parallel specs
After 0040's fixer handed off to the reviewer, its fixer assignment stayed `active`, so `assign` for 0042's backend batch was refused for overlapping paths.
**Resolved (0.8.2):** a handoff from implementer, fixer or toolsmith to another role releases that role's active assignments.

### 52. One role per record serializes fixer and toolsmith
0040's test round produced 3 bugs and 1 tool gap at once. The record holds one current role, so the toolsmith (tool gap) has to wait for the fixer, though they could work in parallel on disjoint lanes. Similarly, an executor told "don't hand off" keeps its lane until the parent releases it.
- **Fix:** allow concurrent sub-assignments on one record (fixer + toolsmith) with disjoint lanes, joined before retest; and release a writer lane automatically when its agent reports completion without handoff (or warn in `overlap --plans`).

**Resolved (0.8.4):** `assign --role toolsmith --alongside` runs a toolsmith beside the active fixer on a disjoint lane (`side_role`), ending with `tracker join`; handoffs to review or test wait for the join. A finished agent's claim no longer blocks the next agent (`brief` reissues it). Not done: auto-releasing a writer lane when its agent stops without a handoff. The tracker can't see agent completion, and a SubagentStop hook would also release the lane of an executor that is paused between batches or waiting for an answer, which the parent resumes with the lane intact. A cross-spec conflict is visible in `overlap --plans` and solved with `assign --release` or `--carve`.

## 53. spec-sync bumps generation and orphans the stored plan (open)
After `spec edit` + `spec-sync` on a plan_ready record, `assign --from-plan` fails "no plan stored": plans are filtered to the current generation. Workaround: re-store the same text with `plan add`. Fix: carry the latest plan forward on spec-sync (or let `plans.latest` fall back to the newest plan when no plan matches the generation).
**Resolved (0.8.4):** spec-sync keeps the generation and the plan (marked `stale` when requirements changed).

## 54. Lane overlap check flags wildcard globs as overlapping whole directories (open)
`be/internal/compute/workspace*.go` was reported to overlap `be/internal/compute/docker/guard.go` and `be/internal/compute/volume.go`. Overlap should be decided by glob intersection (a `*` never crosses `/`, and a literal prefix must match), not by directory prefix.

## 55. `assign --from-plan --batch N` uses the whole plan's ownership on non-early records (open)
`--batch` was ignored and all 8 batches' files were requested. Fix: honor `--batch` for every record, so a parent can run disjoint batches beside another spec's lane.

## 56. `spec edit` can't change a draft's frontmatter (title, amends)

Editing draft 0048 (m33) into "Workspace Read API", which amends 39, 40 and 47, left `title: Workspace Explorer` and `amends: []`, because `edit --from` replaces only the body and there is no `link`/`retitle` command. Proposal: `spec edit <id> --title ... --amends ... --references ...` for unaccepted specs, recorded in the log like body edits.

## Retro 0.8.2 (m33 session b43fa2d7, specs 0036–0050)

### 57. Opus fixers with bundled bugs are the largest cost (retro: fixer.tier)
Since 0036, fixers took 33% of subagent cost (39.7M of 117.9M cost units, 15 runs). Five Opus first-round fixers took 6.1–7.9M each, with 151–243 tool calls and 244–424k final context (0038 large output, 0039 BUG-021, 0040 bugs 001-009, 0042 bugs 001-005, 0045 bugs 001-004). The orchestrator says fixers run on the efficient tier and escalate to Opus only after a failed retest, but the parent picked Opus for first rounds.
- **Fix:** `brief --role fixer` takes at most ~4 bugs or one area per fixer (split the rest across fresh fixers on disjoint lanes). Opus is allowed only via `--escalate` after a failed retest or for a critical bug. A fixer that passes ~150k context hands back.

### 58. Final executor batches balloon (retro: executor.final-batch)
A resumed executor that takes the last 3–4 batches is the most expensive run of its spec: 0038 b5-7 5.8M/167 calls/410k context, 0039 b9-11 5.8M/211/386k, 0045 b2-5 3.5M/130/308k, 0040 b10-11 3.2M/124. Earlier batches cost 0.8–2.0M.
- **Fix:** at most 2 batches per executor (`brief --batch N` refuses a third on the same assignment without `--fresh`). Split integration/testability batches from feature batches in the plan.

### 59. Planners read like implementers (retro: planner.cost)
9 Opus planners cost 18.6M (15%) with 215–416k final context and 52–104 calls. That is about 57% of implementer cost for the same specs.
- **Fix:** planner gets a context budget (~150k) and a repo-map step (`rg --files`, `grep -n` symbol lists) before any full read. Findings cite file:line from grep, not whole-file reads. Hypothesis: most of the context is full-file reads of the existing code.

### 60. Orchestrator forbids pointer briefs that the parent always uses (retro: prompts.not-brief)
57 of 61 recent non-marker prompts were pointer-style (`cat <brief file>`), against orchestrator SKILL.md step 7 ("Never send a pointer"). Pasted briefs were only 280–860 tokens here, so pasting is cheap. Either enforce pasting or accept pointers (#42); right now the rule and practice disagree, and the retro counts 100 false violations.
- **Fix:** decide one way. If pointers are allowed, `brief --out <file>` writes the marker on line 1, the hook and the retro rule accept a prompt that names such a file.

### 61. Retro script accuracy (retro: script.accuracy)
- Plugin-dev runs ("Plugin 0.8.0: spec parallelization", "Build spec-workflow 0.7.0", "Add toolsmith/test-toolkit") are not tagged `plugin_dev`; 2 of the top 3 `cli.rejections` sources are plugin-dev runs.
- "Planner: 0047 file viewer" is attributed to 0046.
- `--compare` against a retro of the same long-running session compares cumulative totals; it should need disjoint `--since/--until` windows or warn.
- Common shell failures that are not covered: exit 127 from `gofmt`/`jq`/`psql` run without the direnv prefix and from `T="python3 ..."; $T` (zsh no word split), exit 144 from `pkill -f` matching its own shell (4×). Add these to the bash failure classifier with a fix hint.

**Resolved (0.8.4):** plugin-dev runs are detected by description (non-spec roles) and by writes to plugin source; a run's spec comes from its claim, then tracker commands, the brief, the description, the prompt, and spec files read, and only existing `NNNN-<slug>` names count as features. Runs belong to the window they start in, and `--compare` refuses overlapping reports without `--force`. Exit 144 `pkill -f` and exit 127 (missing toolchain prefix, zsh word split) are classified with fix hints.

## 57. Concurrent `toolkit update --command` overwrites other specs' additions

In m33, lanes for 0046, 0047 and 0051 each updated the shared `be-inspect` entry by rewriting the whole `--command` string, so each one dropped the others' documentation, and `toolkit verify` still passed. Proposal: store per-spec capability notes (`--capability` keyed by owner spec) instead of one free-text command, or have `update` refuse when the entry changed since the caller last read it.

## 58. `spec new --supersedes 0` is accepted and marks spec 0000

`spec new ... --supersedes 0` (a typo for "none") wrote `supersedes: [0]` into the new spec. The guard hook then blocks every way to fix the frontmatter of an unaccepted spec (see #56). `new` should reject 0 when the user meant none, or `edit` should be able to change links.

### 62. spec-sync also drops the stored plan and pulls in amended targets (retro: tracker.spec-sync)
m33, 2026-10-28: two mid-run user amendments (0059 R6, 0060 R3) each needed spec-sync. Each sync reset every implemented mark (13 and 20 requirements; extends #44) and deleted the stored plan, so `brief --batch N` failed with "no plan stored" until the parent re-added it from a saved `plan show` copy. The 0060 sync also imported 4 amended-target requirements (38:R6, 40:R2, 46:R4, 51:R6) that the original import, without `--include-amended`, had skipped. Each sync cost one re-marking agent round plus 4–6 parent tracker calls.
- **Fix:** spec-sync keeps the plan (it marks it `stale` when a changed requirement appears in a batch) and invalidates only the changed requirements (#44). `init`/`requirement import` should include amended targets by default, so requirements don't appear mid-run.

**Resolved (0.8.4):** spec-sync keeps the plan and marks it `stale` (status, brief warning; `brief --batch N` still works), invalidates only changed/new requirements, and import includes amended targets by default (`--exclude-amended` opts out).

### 63. A fresh agent can't claim an assignment a finished agent still holds (retro: tracker.stale-claim)
m33 0060: a batch-3 implementer launched on the same assignment as the finished batch 1–2 implementer was refused ("already claimed by another agent") and stopped. That cost one launch, plus a release and re-assign. This is not the usage-limit case in #46: the earlier agent had completed normally.
- **Fix:** `brief` for a role whose assignment is claimed by an agent that is no longer running should reissue the assignment, or say "use --fresh". Alternatively, an agent's final report (no handoff) releases its claim but keeps the lane.

**Resolved (0.8.4):** `brief` reissues an assignment an earlier agent claimed, with a warning; documented beside `claim` in spec-tracker SKILL.md.

### 64. Cross-spec lane overlap forces patch handoffs (retro: lanes.cross-spec)
m33: the 0062 fixer needed fe/tests/support and fe/tools/lib, which the concurrent 0060 implementer's coarse lane (`fe/tests/**`, `fe/tools/**`) owned. `assign` refused, so the fixer wrote 5 patches and the parent applied them, then resumed the fixer to verify. That added a parent round and a verification gap: the patched infrastructure ran unverified while 0060 kept testing. The same happened earlier with 0059 and request.ts.
- **Fix:** plans should declare lanes by file, not `dir/**`, for shared test infrastructure. `assign` should allow a narrow sub-lane carve-out (`--carve fe/tests/support/** from ASSIGN-x`) with both agents notified.

**Resolved (0.8.4):** planning guidance owns shared test infrastructure by file or narrow subdir; `assign` overlap errors list exact pairs, narrow non-overlapping globs, and a carve command; `assign --carve <glob> --from <ASSIGNMENT>` moves a narrow glob between lanes, recorded on both and shown in the giving lane's brief.

### 65. Serial test suites dominate wall time (retro: tests.serial)
m33, 2026-10-28: before 0062, each Playwright suite ran with 1 worker on `next dev`. The 0059 implementer spent most of its 100 min waiting on serial e2e and audits, and its tester could not run full e2e at all, because `next dev` refused to start beside the dev server. After 0062: mobile went from 379 s to 150 s, mobile-audit from 84 s to 19 s, and e2e now runs at all (about 88 s). Covered in 0.8.3 skill text (test.runner, Parallel testing).
- **Follow-up:** the retro script should measure Bash wall time per category (test/build/lint) per run, so test waiting shows up as a number. Today `wall_seconds` spans from first to last activity, including idle time across resumes (the 0040 fixer shows 754 min). Report active time separately.

**Resolved (0.8.4):** the retro reports `active_seconds` (API + tool time) beside wall time, Bash seconds per test/build/lint/other (also in by-role tables), and a `tests.waiting` finding when test+build exceeds 40% of a run's active time.

### 66. Lane overlap treats `*` as crossing directories (retro: lanes.glob-star)
**Resolved (0.8.4):** overlap now also compares segment-depth ranges (`depth_range`), so `dir/*.go` no longer overlaps `dir/sub/**` or files in `dir/sub/`.
**Also (0.8.4):** a literal path overlaps a glob only when the glob selects it or it is a directory above the glob (`policy-form.spec.ts` no longer overlaps `explorer-*.spec.ts`).
m33, 2026-10-29: `assign --paths be/internal/compute/egressproxy/proxy_test.go` was refused as overlapping `be/internal/compute/*.go` held by another lane. `*` should match within one path segment and only `**` should cross directories, as the hook's own help says. Workaround used: `--carve` from the other lane.
- **Fix:** use segment-aware glob matching in the overlap check, with a test for `dir/*.go` against `dir/sub/x.go`.

### 67. An executor running `brief --batch N+1` reissues its own assignment
m33 0049: the implementer generated the next batch's brief itself, as the parent told it to. The 0.8.4 stale-claim rule then reissued its own claimed assignment (-003 → -004), and it had to re-claim. `brief` should not reissue an assignment when the caller is the agent holding the claim, using the agent-id marker from the hook, or `--same-agent`.

### 68. A fix round clears every tested mark, even for test-only fixes (retro: tracker.retest-scope)
m33 2026-10-29: in 0060 (BUG-004) and 0062 (BUG-005/006/007), the fixes changed only test files, yet each fixer round cleared all of the tester's `tested` marks. The tester then had to re-mark 19 and 10 requirements from unchanged evidence, which cost an extra tester round each time. A failed check that was later superseded by passing evidence under another name also kept blocking the gate.
- **Fix:** a fixer round invalidates only the requirements linked to the fixed bugs (`bug add --requirement`), plus any whose `implemented` location files changed. When every changed file is a test file, keep the tested marks. `gate acceptance` should list a failed check that a newer passing check supersedes, and let the tester mark it superseded rather than re-record it.

### 69. An edit outside the lane got through
m33 0052 batch 1: the implementer edited `be/internal/database/compute_leases_integration_test.go`, which was not in its lane (only `compute_policies.go` was), and the path-guard hook didn't block it. The likely route is a Bash-based edit (sed or a heredoc) that the hook doesn't inspect, or a gap in matching literal paths. Investigate which tool was used, and make sure `guard_paths.py` also covers Bash writes or flags them in the record.
- 2026-10-29 again: the 0052 batch 8 implementer edited fe/tests/e2e/design-system.spec.ts outside its lane and was not blocked.

### 70. Repeated `assign --carve` replaces the receiving lane instead of adding to it
m33 2026-10-29: three `assign --role fixer --carve <glob> --from X` calls each created a new fixer assignment, released the previous one, and lost its carved glob. A following `--paths` call replaced the lane again. The giving lane kept all three exclusions. Expected: `--carve` adds the glob to the role's active assignment, and `--paths` combined with `--carve` in one call builds a single lane.

### 71. Toolkit taxonomy lacks a backend driver capability
A protocol driver (0055 `stt-drive`: WebSocket client with expectations) had to register as `be.fault`. Add `be.drive` (and `fe.drive` if missing) to the capability taxonomy and `toolkit verify`.

### 72. `spec edit` cannot change a draft's links
`spec edit` keeps the frontmatter, so a draft whose review adds `amends`/`depends_on`/`references` (0070 needed `amends: [34]`) can't be fixed; `spec new` with repeated `--depends-on` also kept only the last value silently. Add `spec link <id> --depends-on/--amends/--references` for non-accepted specs, and reject or merge repeated link flags in `spec new`.

### 73. `assign --from-plan --batch N` claims the whole plan's ownership
Assigning batches 3-8 of 0072 (all backend) claimed every fe file in the plan too, blocking a parallel fe lane of another spec; a rejected assign also left the brief reissuing the old lane. Scope `--from-plan --batch` to the selected batches' files, and make `brief` fail when the last `assign` was rejected.

**Resolved (0.10.2):** `--from-plan --batch N` claims only the batch's `**Files:**` paths inside the ownership (backticks optional), falling back to the whole ownership with a warning; `--parallel` lanes are then usable. The rejected-assign brief part stays open.
### 74. Wording-only spec edits force an implementer round trip
After `spec-sync` re-imported two requirements for a wording-only R1 edit (code unchanged), the parent could not re-mark them: `--evidence-from` rejects parent-recorded checks and checks from earlier generations. Allow the parent light path to reuse the latest passed check of the previous generation when the requirement text changed but no code did (with a reason).

### 75. Failed checks can't be waived, and carve rejects zsh-unsplit path lists (parent friction)
- `check waive` only accepts a `not_run` check, so a check that failed for another spec's reason (a parallel lane's regression) can only be cleared by fixing the other lane and re-running. Consider `check waive --supersede-failed` with a recorded cause and owner spec.
- `assign --paths $VAR` in zsh passes one argument containing spaces; the tracker stores it as one bogus glob instead of rejecting it. Reject paths containing whitespace.

## Throughput (m33 run 2026-10-30: "why are features slow?")

About 17 h of agent wall time over 57 runs; tests and builds ≈30% of active time. The time went to serial scheduling, review ping-pong, and one shared working tree, not to testing.

### 76. One shared working tree couples every spec
In-progress code from one spec broke another's checks (0081's decoder change blocked 0085's handoff), lanes fought over shared files (stack.go, config.go, main.go) and needed carves, every full-suite run hit unrelated failures, and a subagent auto-migrated the dev DB by running cmd/server with be/.env.
- **Fix:** worktree mode (`implementation/workspace.json`). Each code repo is a folder of branch checkouts: `<repo>/main` (accepted code) and `<repo>/<branch>` per spec. `tracker worktree create|status|merge|remove`; handoffs from writers commit a checkpoint; merge in acceptance order; dev deploys only from `main`. Lanes are per worktree, so specs no longer contend for files.

### 77. Tests from parallel specs overload the machine
The laptop runs one Docker test stack comfortably. Implementation and review can run in parallel; testing must not.
- **Fix:** `test_slots` in workspace.json (default 1). `brief --role tester` refuses while another spec's tester holds a slot.

### 78. Serial, tiny batches per spec
0081 took 13 executor runs (≈7.2 h) back to back. Plans had 9–12 small batches, each a fresh agent re-reading spec, plan, and code; be and fe batches with disjoint files couldn't run together.
- **Fix:** planners aim for 3–5 batches; `assign --parallel` runs several executors of one spec on disjoint lanes (e.g. be and fe), joined at the handoff to review.

### 79. Review → fix → re-review ping-pong on small findings
0085 (small) took 6 review rounds for 9 mostly-low bugs. Each round is a fix, a fresh review, and a retest.
- **Fix:** risk tiers (`tracker risk <feature> high|normal`). High (security, data, migration, concurrency) keeps fresh reviewers every round. Normal: one full review, then the same reviewer resumed on the fix diff. `bug follow-up` moves low bugs (medium with a user decision) out of the acceptance gate into a follow-up list.

### 80. Full suites at batch boundaries; fragile environment
Full-suite runs at every batch boundary, and ≈3.5 h of toolsmith time on Docker address pools, missing browser libraries, and racing restarts.
- **Fix:** focused tests per batch; full suite once by the tester before acceptance and preflight after each merge. Preflight should check environment health (stale networks and stacks) before a run. Projects should make the server refuse auto-migration without an explicit flag.

### 81. Retro flags most of a normal run as plugin development (open)
The 2026-10-30 retro tagged 41 of 57 runs `plugin_dev`, so its per-spec table covered two specs. Check the 0.8.4 plugin-source-write detection against runs that only call the CLIs from a local marketplace checkout.

### 82. Parallel executor handoff released its siblings' lanes (0.10.0–0.10.2)
In 0082 batch 4's executor ran `handoff --to parent` while batch 6's executor (`--parallel`) was working; the handoff released every executor lane. A later `brief` for a batch without its own lane reissued a sibling's lane, and the next `assign --parallel` then collided with it.
**Resolved (0.10.3):** `join --assignment`, the handoff refusal while siblings are active, and the batch-lane check in `brief`.

### 83. Copied `.env` pointed spec checkouts at the dev database (0.10.0–0.10.5)
The suggested `copy: {"be": [".env"]}` gave every checkout the dev `DATABASE_URL`; an agent in a spec checkout migrated the dev database to the branch's migration 51 before merge.
**Resolved (0.10.6):** `env` overrides in workspace.json and a procedures rule; m33 also rewrites the URL in a `setup` step.

### 84. m33 0082/0087/0088 run friction (0.10.6)
Multi-directory smokes broke under the worktree rewrite (`cd ..`, `direnv exec fe`); a late reviewer re-record of a `not_run` check forced a no-op tester round; `restore` reset all 16 requirements for a 2-defect fix; the parent couldn't file final-review bugs.
**Resolved (0.10.7):** idempotent rewrite with `direnv exec` and `cd ..` handling; ordering exemption for same-generation re-runs of `not_run` reviewer checks; `restore --touches`; `bug add --parent-confirmed --found-by`.

### 85. Hand-scheduled test slot, late merge conflicts, repeated full suites (0.10.7)
The parent hand-scheduled the single test slot; 0082 and 0087 both took migration 52 and the 11 conflicts surfaced only after 0087's test; agents ran full suites repeatedly.
**Resolved (0.11.0):** local PRs (`pr open`: commits, merge-tree against main, PR checks, fast CI), re-checks of open PRs whenever main moves with a built-in duplicate-number hook, review/test/merge queues with slot classes, leases and `queue wait`, and the merge queue (`queue run merge`).
