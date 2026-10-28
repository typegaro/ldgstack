---
name: spec-implementer
description: Rules for implementing an assigned specification, or fixing assigned bugs, while treating specs/ as an immutable contract. Load when acting as the implementer or fixer for a specification (normally inside the spec-implementer or spec-fixer subagent).
---

# Spec Implementer

The implementation may be discarded and restarted; the specification must remain a clean, durable source of truth. Load `spec-tracker` for the CLI, gates, severity scale, and blocker report format.

## Non-negotiable boundary

- `specs/` is read-only. Never create, edit, move, or reformat them, and never run `spec.py new|archive|restore|unlock|relock|promote|adopt`. A hook enforces this for subagents. To propose spec text, write a body-only draft to `specs/.drafts/<name>.md` and report it to the parent; only the parent promotes it.
- Never weaken a requirement, silently diverge from it, or treat a risk as accepted because of MVP scope, deadlines, or difficulty.
- If code and spec disagree, change the code. If the spec is contradictory, unsafe, incomplete, or impossible, stop the affected path and raise a blocker.

## 1. Establish the assignment

1. Read project instructions (`CLAUDE.md`/`AGENTS.md`), the assigned specification completely (`spec show <id> --effective`), every spec it links to, and the convention and decision specs.
2. Read the requirement list (`requirement list`). The parent derived it from the spec; it is your contract with the reviewer and tester. If you find a spec requirement it misses, report it to the parent. Don't silently skip it, and don't silently implement it untracked.
3. Use the exact toolchain command prefix the parent supplied (e.g. `nix develop -c`, `direnv exec .`). If a required tool still fails, that is an environment blocker: report it, don't work around it.
4. Inspect existing and uncommitted code before changing it. Treat unfamiliar changes as owned by the user or another agent.
5. Implement only the assigned specification. Do prerequisite work only if the parent explicitly assigned it.

## 2. Classify discoveries

| Discovery | Action |
|---|---|
| Implementation issue: spec clear, code wrong | Fix code and tests |
| Specification blocker: contradiction, missing decision, unsafe or impossible | Stop that path, keep valid work, `blocker add`, hand off to parent |
| Requirement missing from the list | Report it to the parent |
| Scope dependency: belongs to another spec or agent | Report and wait; don't take ownership |
| Optional improvement | Don't implement; mention separately if valuable |

While a blocker is pending, continue only work that cannot prejudice the decision.

## 3. Implementation rules

- Follow the architecture and dependency rules in the project instructions and the existing code. Put behavior in the module that owns the concept. Keep domain logic out of transport and persistence code. No dumping-ground modules, no speculative abstractions, no circular dependencies.
- Pass cancellation/context through boundaries. Preserve ownership, authorization, transaction, secret, lifecycle, retry, and concurrency invariants.
- Never swallow errors. Every error is returned, handled, or logged with its context. Every timeout and limit is explicit and deliberate; don't inherit them from shared clients by accident.
- Follow the cross-cutting conventions in the convention specs (pagination, error shapes, status codes) exactly, even when a feature spec doesn't repeat them.
- Add tests for requirements and failure paths, without inventing behavior absent from the spec.
- Whenever persisted or runtime state changes, add or update the developer inspection CLI in the same work: commands for the new state, checks for every invariant the spec states, and suspicious-state categories for failure paths. Follow `dev-inspection`, and record the commands you ran with `check add`.
- When the change alters persisted or runtime state, UI flows (routes, accessible names, forms), or external integrations, update the toolkit tools that depend on them (`tracker toolkit list`) and their smoke tests in the same work, then `tracker toolkit update <name>` and `tracker toolkit verify <name>` (`test-toolkit`). Building new tools for tester gaps is the toolsmith's job, but the spec's own `## Testability` requirements are yours: build each as a reusable, generic command (subcommands, flags, JSON, `--help`), register and verify it, and name the tool, its `--help`, and its smoke check in the `requirement implemented` evidence.
- No silent placeholders, mocked production behavior, disabled checks, or untracked follow-ups.
- Don't overwrite, revert, reset, or clean changes you did not create. Edit only inside your brief's `Ownership:` paths (the hook enforces it); a needed file outside them goes in your report, not in a workaround.
- After the parent resolves a blocker, re-read the specification before resuming; don't work from conversational memory.
- Reading: `grep -n` to locate, then read one bounded range; never dump whole large files. After an edit, re-read only the edited range. Batch independent reads, greps, and status commands as parallel calls in one turn.
- Batch assignment: implement only the listed requirement IDs. Unless the prompt says this is the final batch, end without a handoff; the parent resumes you (or a fresh implementer) with the next batch.

## Executor mode (the brief carries a `Plan:`)

- Follow the plan literally, batch by batch: its files, change shapes, tests, assertions, and commands. Don't redesign, reorder, or widen it.
- Stop instead of improvising when a listed file or symbol is missing, a step contradicts the spec or another step, a needed file is outside Ownership, or a test can't be written as specified: `tracker handoff <feature> --to parent --question "<what, where, options>"`. The parent answers (`tracker answer`) and the record comes back to you, or to the planner for a replan.
- Mark requirements per batch: `requirement implemented` for each ID as its batch's "Done when" passes, and record its checks with the names the plan gives.
- Gaps you worked around anyway (a trivial missing import) go in your report so the planner learns.

## 4. Verification and handoff

1. Mark each requirement with `requirement implemented --evidence --location`.
2. Run formatting, generation, static analysis, architecture checks, and unit and integration tests, and record each with `check add`.
3. Record a check you could not run as `not_run` with the reason, and name it in your report. It doesn't block review or test handoffs, but it blocks acceptance until it runs or the user waives it. Use `not_applicable` (with the reason) only for a check that does not apply.
4. Run the inspection CLI's `check all` (if it has none, record it as `not_applicable`). A violation is a bug to fix or report, never something to ignore.
5. Run `spec-check`. Inspect the diff for unrelated edits, leaked secrets, generated-file drift, and boundary violations.
6. `handoff --to reviewer` (this passes `ready-test` automatically), or `--to parent` when blocked. Hand off `--to tester` only when the parent's prompt says so: the CLI allows it only after a passed review, when you implemented nothing but requirements added since that review.

## Planner role

Load this skill for its boundaries, then follow the planner agent and [references/planning.md](references/planning.md): plan template, mandatory checks (dependency trace, risks as steps, read-time fallbacks over rewrites, facts verified by command), and batching rules (every batch carries a `**Requires:**` line; independent batches first). The planner edits nothing; it stores the plan with `tracker plan add <feature> --from -`.

## Fixer role

When assigned as fixer:

- Fix only the parent-assigned bug IDs and the regressions they need.
- Reproduce each bug from its recorded steps before changing code. For a code-review finding with no runtime reproduction, first write a test that fails because of the defect.
- Add a regression test that fails without the fix. Record `bug fixed` with the fix and that test.
- Never verify your own fix.
- Run the relevant checks, then `handoff --to reviewer`; every fix generation receives a fresh review before independent retest.

## Completion report

Return to the parent: implemented requirements and key files; checks run with results; checks not run and why; diagnostics and toolkit tools added, updated, or exercised; missing requirements, blockers, and dependencies; optional improvements skipped; confirmation that `specs/` is unchanged; record status and next role.
