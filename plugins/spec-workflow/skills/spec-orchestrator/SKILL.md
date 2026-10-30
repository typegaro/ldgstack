---
name: spec-orchestrator
description: Autonomously implement every numbered specification in specs/ in dependency order, delegating implement → code review → independent test → fix → retest to subagents and archiving each accepted spec. Use when the user asks to implement all specs, continue the spec run, or reimplement an archived spec.
---

# Spec Orchestrator

You are the parent. Run this in the main session; only the main session can delegate to subagents. Load `spec-cli` for spec history and `spec-tracker` for implementation records. Procedures (light path, audited spec edits, dependency guard, lanes, resuming, completion, releasing): [references/procedures.md](references/procedures.md).

Below, `spec` means `python3 <spec-cli skill base directory>/scripts/spec.py` and `tracker` means `python3 <spec-tracker skill base directory>/scripts/spec_tracker.py` (or the plugin's `bin/spec` and `bin/spec-tracker` wrappers). Spell the full command out in every Bash call: shell state doesn't persist between calls, and zsh doesn't word-split `$SPEC`.

```bash
spec validate | status | ready | next | waves | list | show <id> --effective | log <id> | preflight
spec edit <id> --from specs/.drafts/<file>.md --reason "..." [--user-decision "..."] --parent-confirmed
spec archive <id> --parent-confirmed
spec restore <id> --reason "..." --parent-confirmed
spec defer <id> --reason "..." --parent-confirmed   # park a draft; undefer <id> to resume
```

## Source of truth

- `specs/NNNN-<slug>.md` files are applied like migrations, in dependency order: a spec is ready when every spec it `depends_on` or `amends` is accepted (`spec ready`; `next` is the lowest ready id). `tracker init` refuses anything else without `--early` (see Parallel scheduling) or a recorded user decision. A `deferred` spec is skipped everywhere until `spec undefer`. `convention` specs bind every later unit. `decision` specs have no implementation: archive them once the user has accepted them.
- An accepted spec is frozen. Changes arrive as new specs that amend or supersede it. Their tester also re-verifies the effective requirements of the amended spec.
- Specs never change to fit an implementation. Edits go through `spec edit` (audited, `--user-decision` for in-progress specs and conflict resolutions); the hook denies direct edits.
- The CLIs are the durable state. Never rely on conversation memory, and never edit their JSON or Markdown, or the plugin cache.

## Preflight (before the first delegation, and after any environment change)

`implementation/preflight.json` lists the commands every agent must be able to run, in each repository's real environment, e.g. `{"commands": ["cd be && nix develop -c go version", "cd fe && nix develop -c npx tsc --version"]}`. Create it with the user if missing; include the inspection CLI's `overview` once it exists. Run `spec preflight`, then `tracker toolkit verify` (`test-toolkit`). If preflight fails, stop and ask the user; never delegate into a broken environment. A failing or stale toolkit tool is repaired first (delegate `spec-workflow:spec-toolsmith`, no record needed, or ask the user).

## Loop

1. `validate`, `status`, `preflight`. Every tick, run `spec waves` and `tracker status` and schedule per Parallel scheduling. If no `convention` spec defines the developer inspection CLI, stop and create it with the user (`dev-inspection`, `write-specs`) before the first feature.
2. Take `next` (or another `startable` spec from `waves`). Read `show <id> --effective`, `log <id>`, every linked spec, the convention and decision specs, and project instructions.
3. If it has no record: `init` (leaves the record with the parent; `init --early` for a `plannable` spec). If a record exists, read `status` (including `pending`) and resume the role it needs.
4. **Derive requirements yourself, before any implementation.** `requirement import <feature>` (amended targets included; `--exclude-amended` skips them), read its warnings, then add what import can't see: prose rules without an ID (`requirement add --spec-ref "<id>:<section>"`), touched requirements not cited as `<id>:R<n>`, and sharper `--verification` where a bullet isn't observable.
5. **Plan.** `handoff --to planner` (creates its read-only lane; `--parent-confirmed` also recalls an executor that has implemented nothing), delegate `spec-workflow:spec-planner`; it stores the plan (`plan add`) and hands back (`plan_ready`). Read `plan show <feature>`; send obvious gaps back with `handoff --to planner --remaining "<gap>"`. Required for more than 3 requirements or more than one area; skip only with `handoff --to implementer --parent-confirmed --reason "..."`.
6. **Execute.** `handoff --to implementer`, `assign <feature> --role implementer --from-plan [--batch N] --parent-confirmed`, then `brief --role implementer --batch 1` to a `spec-workflow:spec-implementer` (the executor). Give each plan batch (or 2 small batches) to a **fresh executor** with `brief --batch N+1` (it reissues the assignment once the earlier agent claimed it; `--fresh` forces a new one); never resume one executor across more than ~2 batches or past ~200k context. The record carries state between them; resuming is for small follow-ups, short fixes, and a retest by the same tester. Testability requirements are executor batches, never toolsmith work. The final batch hands off to review.
7. For every delegation, paste the `tracker brief <feature> --role <role>` output **verbatim** as the prompt, appending only extra context below it (never another agent's report for a verifier). Never send a pointer to a brief ("run brief ...", a file path); a hook warns when the marker is missing. `brief` refuses an unbatched implementer brief for more than 10 requirements, more than 2 areas, or a multi-batch plan.
8. **Questions.** On `needs_answer` (`status` shows `open_questions`): answer from the spec, plan, and code with `answer <feature> --text "..."` (back to the asker; resume it with SendMessage and the answer). Design questions, or a wrong plan: `answer --replan` (planner, then `assign --from-plan` again). Ask the user only for decisions listed below.
9. On `ready_for_review`: a fresh `spec-workflow:spec-reviewer`. On `ready_for_test`: a fresh `spec-workflow:spec-tester` (handoff creates its read-only lane).
10. On `needs_tooling`: `handoff --to toolsmith`, delegate `spec-workflow:spec-toolsmith`. When a test round leaves both bugs and tool gaps, run them in parallel: `handoff --to fixer`, assign the fixer, then `assign --role toolsmith --paths <disjoint> --alongside --parent-confirmed` and brief both; the toolsmith ends with `join`, and the fixer's handoff waits for it. when it hands back, resume the tester that recorded the gaps (SendMessage; a fresh tester for reviewer-recorded gaps). To skip a gap, ask the user and `tool-gap defer` it. If a toolkit requirement was routed to the toolsmith anyway, record its gap yourself (`tool-gap add ... --parent-confirmed`), then `requirement implemented --evidence-from toolkit-<name> --parent-confirmed` after it lands.
11. On `bugs_found`: `bug assign` each bug, `handoff --to fixer`, delegate `spec-workflow:spec-fixer`; fixer work advances the implementation generation. Send every fix through a fresh `spec-workflow:spec-reviewer`, then retest by resuming the tester that recorded the bugs or using a fresh tester (always for reviewer-found bugs). Repeat until every bug is verified or closed with a user decision.
12. A reported missing requirement: check it against the spec; if real, `requirement add` (`--parent-confirmed` if the record is with another role) and send the record back to the implementer. After a passed review, an implementer that only implements added requirements may hand off straight to the tester; send a fresh reviewer when they change security, data, or lifecycle behavior.
13. On `blocked`: resolve what the spec answers (`blocker resolve --parent-confirmed`); otherwise stop and ask the user. `not_run` checks don't block review or retest; get them run, or a user waiver, before acceptance.
14. `tracker gate <feature> acceptance && tracker archive <feature> --parent-confirmed && spec archive <id> --parent-confirmed` (both archives recheck their gates).
15. Continue without asking until no numbered spec remains; then follow Completion in the procedures.

## Model tiers and escalation

Use capabilities, not provider-specific names: planner and reviewer use a **deep-reasoning tier**; implementer (executor), fixer, tester, and toolsmith use an **efficient execution tier**. This Claude plugin maps those tiers to `opus` and `sonnet` in agent frontmatter. OpenAI equivalents include GPT-5.6 Terra with `high`/`xhigh` reasoning and GPT-5.6 Sol with `medium`/`high` reasoning. Treat these as examples and map the tiers to the models available in the host.

- An executor that fails the same gate or check twice: `handoff --to parent`, then `handoff --to planner --remaining "<failure>"` (or `answer --replan`).
- A fixer whose fix fails retest: rerun it on the deep-reasoning tier (for Claude, Agent `model: "opus"`; for OpenAI, for example GPT-5.6 Terra at `high`).
- High-risk specs (security, data migration, concurrency): after the normal tester passes, run one extra `spec-tester` pass on the deep-reasoning tier, scoped to edge cases.
- On a retest, `check add` with the failed check's exact name supersedes it; the brief lists those names. A gate error names the role that must re-record a check and the handoff command; never attest a reviewer's or tester's check as the parent.

## Parallel scheduling

Prefer parallel work whenever the dependency graph and lanes allow it. `spec waves` returns `startable` (all `depends_on`/`amends` accepted), `plannable` (draft, every unaccepted dependency is in progress or startable; `blocked_on` lists them), topological `waves`, and `deferred` (ignored).

- **Plan ahead.** Launch planners for `plannable` specs while their dependencies are implemented or reviewed: `tracker init <spec> --early` stores `early` and `blocked_on`, then derive requirements and plan as usual. Planners mark each batch `**Requires:** <ids>|none`.
- **Early batches.** In an early record, `assign --from-plan` and `brief --batch N` refuse a batch whose `Requires` names an unaccepted spec (no line = all of `blocked_on`). Run batches marked `Requires: none` at once; run the rest once those specs are accepted. `gate acceptance` and `archive` wait for all of `blocked_on`. Overrides need `--parent-confirmed --user-decision`.
- **Parallel executors.** Run executors for `startable` specs, and for early `Requires: none` batches, together. First run `tracker overlap --plans`: any pair it reports would edit the same files, so serialize those or narrow the plans. Keep `be/` and `fe/` in separate lanes.
- **Fresh agents per batch.** Long runs cost most (17 runs past 250k context in the 0.8.3 retro): a fresh executor per plan batch (or 2 small batches) and a fresh fixer per ~4 bugs or one area. Resume an agent only for a small follow-up, a short fix, or a retest by the tester that found the bugs.
- **Shared paths across specs.** When `assign` refuses an overlap, use the narrow globs its error lists, or `assign <feature> --role <role> --carve <glob> --from <ASSIGNMENT> --parent-confirmed` to take a narrow glob out of the other spec's active lane (both lanes record it; the other agent's writes there warn, and its next brief shows the carve-out). Tell the other agent with SendMessage if it is running.
- **Pipeline roles.** While spec A is in review or test, spec B's executor runs. Never run two agents on one spec; never combine specs in one agent.
- **Concurrency cap.** Default at most 2 executors/fixers plus 1 deep-tier agent (planner/reviewer/deep tester) at a time; the user may change it. After a usage-limit stop, lower the cap by one and resume the stopped agents with SendMessage instead of restarting them. Stagger starts.
- **Parallel testing.** Agents that test at the same time get distinct ports, build directories, and isolated databases (`env.isolate`). If the project's suites run serially or share fixed ports, schedule a parallel-runner tooling spec (`test.runner`) before the next large spec: slow serial tests dominate spec wall time.
- **Worktrees.** Two specs that are both startable and touch disjoint code (no `tracker overlap`) may run in separate git worktrees, on branches `spec/<NNNN>-<slug>` in each repository, each with its own stack and ports. Merge in acceptance order and renumber colliding migrations at merge time. Don't use worktrees for specs that share hot files or for cross-cutting cleanups.
- **Hygiene.** Each agent gets its own scratch subdir (`$SCRATCH/<role>-<assignment>/`). The parent serializes tracker writes per record (one `tracker` call at a time for a feature) and handles each agent's report as it arrives.
- Lanes stay enforced: `assign` refuses overlapping paths and the hook denies writes outside a lane; run `tracker overlap --depth 2` after each implementer or fixer round. A blocked spec holds only its dependents.

## Independence

- **Never** pass the implementer's or fixer's report, rationale, or summary to the reviewer or tester. Briefs never show the plan to testers; reviewers get a pointer to compare against it.
- Use a fresh agent for every first review and test round. Only a retest may resume the tester that found the bugs.
- For extra independence, run verifiers on a different model (the Agent tool's `model` parameter).

## Decisions that belong to the user

Don't judge your own exceptions. Use AskUserQuestion and record the answer verbatim in `--user-decision` for: waiving a check (a missing toolchain or service is never a reason), closing a bug as not a bug, resolving a blocker the spec doesn't answer, deferring a tool gap, starting a spec before its dependencies are accepted (other than `--early`), running an early batch before its required specs are accepted, and editing an in-progress spec or resolving a conflict between specs (`spec edit`).

## Stop and ask the user when

- Specs contradict each other, or a material product, security, data, lifecycle, or compatibility decision is missing.
- Specified behavior is impossible or unsafe as written.
- Preflight fails, or required external access has no deterministic local substitute and the toolsmith cannot build one.
- Repeated fix attempts make no progress.

Give one consolidated report: exact references, evidence, impact, options, and a recommendation. Never edit specs on your own judgment, accept risks, skip the blocked spec, or continue dependent work.
