---
name: spec-orchestrator
description: Autonomously implement every numbered specification in specs/ in dependency order, delegating implement → code review → independent test → fix → retest to subagents and archiving each accepted spec. Use when the user asks to implement all specs, continue the spec run, or reimplement an archived spec.
---

# Spec Orchestrator

You are the parent. Run this in the main session; only the main session can delegate to subagents. Load `spec-cli` for spec history and `spec-tracker` for implementation records. Procedures (light path, audited spec edits, dependency guard, lanes, resuming, completion, releasing): [references/procedures.md](references/procedures.md).

Below, `spec` means `python3 <spec-cli skill base directory>/scripts/spec.py` and `tracker` means `python3 <spec-tracker skill base directory>/scripts/spec_tracker.py` (or the plugin's `bin/spec` and `bin/spec-tracker` wrappers). Spell the full command out in every Bash call: shell state doesn't persist between calls, and zsh doesn't word-split `$SPEC`.

```bash
spec validate | status | ready | next | list | show <id> --effective | log <id> | preflight
spec edit <id> --from specs/.drafts/<file>.md --reason "..." [--user-decision "..."] --parent-confirmed
spec archive <id> --parent-confirmed
spec restore <id> --reason "..." --parent-confirmed
```

## Source of truth

- `specs/NNNN-<slug>.md` files are applied like migrations, in dependency order: a spec is ready when every spec it `depends_on` or `amends` is accepted (`spec ready`; `next` is the lowest ready id). `tracker init` refuses anything else without a recorded user decision. `convention` specs bind every later unit. `decision` specs have no implementation: archive them once the user has accepted them.
- An accepted spec is frozen. Changes arrive as new specs that amend or supersede it. Their tester also re-verifies the effective requirements of the amended spec.
- Specs never change to fit an implementation. Edits go through `spec edit` (audited, `--user-decision` for in-progress specs and conflict resolutions); the hook denies direct edits.
- The CLIs are the durable state. Never rely on conversation memory, and never edit their JSON or Markdown, or the plugin cache.

## Preflight (before the first delegation, and after any environment change)

`implementation/preflight.json` lists the commands every agent must be able to run, in each repository's real environment, e.g. `{"commands": ["cd be && nix develop -c go version", "cd fe && nix develop -c npx tsc --version"]}`. Create it with the user if missing; include the inspection CLI's `overview` once it exists. Run `spec preflight`, then `tracker toolkit verify` (`test-toolkit`). If preflight fails, stop and ask the user; never delegate into a broken environment. A failing or stale toolkit tool is repaired first (delegate `spec-workflow:spec-toolsmith`, no record needed, or ask the user).

## Loop

1. `validate`, `status`, `preflight`. If no `convention` spec defines the developer inspection CLI, stop and create it with the user (`dev-inspection`, `write-specs`) before the first feature.
2. Take `next` (or another spec from `ready`, see Concurrency). Read `show <id> --effective`, `log <id>`, every linked spec, the convention and decision specs, and project instructions.
3. If it has no record: `init`, then `handoff --to parent`. If a record exists, read `status` (including `pending`) and resume the role it needs.
4. **Derive requirements yourself, before any implementation.** `requirement import <feature> --include-amended`, read its warnings, then add what import can't see: prose rules without an ID (`requirement add --spec-ref "<id>:<section>"`), touched requirements not cited as `<id>:R<n>`, and sharper `--verification` where a bullet isn't observable.
5. **Plan.** `handoff --to planner` (creates its read-only lane), delegate `spec-workflow:spec-planner`; it stores the plan (`plan add`) and hands back (`plan_ready`). Read `plan show <feature>`; send obvious gaps back with `handoff --to planner --remaining "<gap>"`. Required for more than 3 requirements or more than one area; skip only with `handoff --to implementer --parent-confirmed --reason "..."`.
6. **Execute.** `handoff --to implementer`, `assign <feature> --role implementer --from-plan --parent-confirmed`, then `brief --role implementer --batch 1` to a `spec-workflow:spec-implementer` (the executor). After each non-final batch, resume **the same executor** with SendMessage and the pasted `brief --batch N+1`, or give the batch to a fresh executor with `brief --batch N+1 --fresh` (new assignment, same paths). Testability requirements are executor batches, never toolsmith work. The final batch hands off to review.
7. For every delegation, paste the `tracker brief <feature> --role <role>` output **verbatim** as the prompt, appending only extra context below it (never another agent's report for a verifier). Never send a pointer to a brief ("run brief ...", a file path); a hook warns when the marker is missing. `brief` refuses an unbatched implementer brief for more than 10 requirements, more than 2 areas, or a multi-batch plan.
8. **Questions.** On `needs_answer` (`status` shows `open_questions`): answer from the spec, plan, and code with `answer <feature> --text "..."` (back to the asker; resume it with SendMessage and the answer). Design questions, or a wrong plan: `answer --replan` (planner, then `assign --from-plan` again). Ask the user only for decisions listed below.
9. On `ready_for_review`: a fresh `spec-workflow:spec-reviewer`. On `ready_for_test`: a fresh `spec-workflow:spec-tester` (handoff creates its read-only lane).
10. On `needs_tooling`: `handoff --to toolsmith`, delegate `spec-workflow:spec-toolsmith`; when it hands back, resume the tester that recorded the gaps (SendMessage; a fresh tester for reviewer-recorded gaps). To skip a gap, ask the user and `tool-gap defer` it. If a toolkit requirement was routed to the toolsmith anyway, record its gap yourself (`tool-gap add ... --parent-confirmed`), then `requirement implemented --evidence-from toolkit-<name> --parent-confirmed` after it lands.
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

## Concurrency

- Specs ready at the same time are independent; run them concurrently, one agent at a time per spec, at most 2 heavy lanes, with staggered starts. Prefer pairs in different repositories (`be/` and `fe/`).
- Lanes are enforced: `assign` refuses overlapping paths and the hook denies writes outside a lane. Run `tracker overlap --depth 2` after each implementer or fixer round.
- A blocked spec holds only its dependents; independent ready specs continue.

## Independence

- **Never** pass the implementer's or fixer's report, rationale, or summary to the reviewer or tester. Briefs never show the plan to testers; reviewers get a pointer to compare against it.
- Use a fresh agent for every first review and test round. Only a retest may resume the tester that found the bugs.
- For extra independence, run verifiers on a different model (the Agent tool's `model` parameter).

## Decisions that belong to the user

Don't judge your own exceptions. Use AskUserQuestion and record the answer verbatim in `--user-decision` for: waiving a check (a missing toolchain or service is never a reason), closing a bug as not a bug, resolving a blocker the spec doesn't answer, deferring a tool gap, starting a spec before its dependencies are accepted, and editing an in-progress spec or resolving a conflict between specs (`spec edit`).

## Stop and ask the user when

- Specs contradict each other, or a material product, security, data, lifecycle, or compatibility decision is missing.
- Specified behavior is impossible or unsafe as written.
- Preflight fails, or required external access has no deterministic local substitute and the toolsmith cannot build one.
- Repeated fix attempts make no progress.

Give one consolidated report: exact references, evidence, impact, options, and a recommendation. Never edit specs on your own judgment, accept risks, skip the blocked spec, or continue dependent work.
