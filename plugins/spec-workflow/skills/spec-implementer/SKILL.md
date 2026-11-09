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

- Open your first message by restating the spec's goal and the smallest change you expect to meet it. Load `engineering-principles` and cite the ones that shaped a decision in your handoff; load `go-practices` or `typescript-practices` for the files you touch.
- Name the data shape before writing logic (`data-shape-first`, `model-the-domain`): a state machine over scattered booleans, a table over a growing `if` chain, a typed model over repeated shape assumptions.
- Write the smallest change that meets the requirement (`smallest-change`). Line count is never a goal on its own: the right amount of code is whatever the requirement and the conventions need.
- Follow the architecture and dependency rules in the project instructions and the existing code. Put behavior in the module that owns the concept. Keep domain logic out of transport and persistence code. No dumping-ground modules, no speculative abstractions, no circular dependencies.
- Pass cancellation/context through boundaries. Preserve ownership, authorization, transaction, secret, lifecycle, retry, and concurrency invariants.
- Never swallow errors. Every error is returned, handled, or logged with its context. Every timeout and limit is explicit and deliberate; don't inherit them from shared clients by accident.
- Follow the cross-cutting conventions in the convention specs (pagination, error shapes, status codes) exactly, even when a feature spec doesn't repeat them.
- Add tests for requirements and failure paths, without inventing behavior absent from the spec.
- Whenever persisted or runtime state changes, add or update the developer inspection CLI in the same work: commands for the new state, checks for every invariant the spec states, and suspicious-state categories for failure paths. Follow `dev-inspection`, and name the commands you ran in your `done` summary.
- When the change alters persisted or runtime state, UI flows (routes, accessible names, forms), or external integrations, update the toolkit tools that depend on them (`tracker toolkit list`) and their smoke tests in the same work, then `tracker toolkit update <name>` and `tracker toolkit verify <name>` (`test-toolkit`). Building new tools for tester gaps is the toolsmith's job, but the spec's own `## Testability` requirements are yours: build each as a reusable, generic command (subcommands, flags, JSON, `--help`), register and verify it, and name the tool, its `--help`, and its smoke check in the `requirement implemented` evidence.
- No silent placeholders, mocked production behavior, disabled checks, or untracked follow-ups.
- Don't overwrite, revert, reset, or clean changes you did not create. Edit what the brief's `Ownership:` allows: in worktree mode any file in your spec's checkout (edit what the change needs, including files the plan didn't list, and name them in your handoff); without worktrees, only your lane's paths.
- After the parent resolves a blocker, re-read the specification before resuming; don't work from conversational memory.
- Reading: `grep -n` to locate, then read one bounded range; never dump whole large files. After an edit, re-read only the edited range. Batch independent reads, greps, and status commands as parallel calls in one turn.
- Batch assignment: implement only your batch's requirement IDs, then `done`; the parent starts the next batch.

## Executor mode (the brief carries a `Plan:`)

- Follow the plan literally, batch by batch: its files, change shapes, tests, assertions, and commands. Don't redesign, reorder, or widen it.
- Stop instead of improvising when a listed file or symbol is missing, a step contradicts the spec or another step, a needed file is outside Ownership (only without worktrees), or a test can't be written as specified: `tracker handoff <feature> --to parent --question "<what, where, options>"`. The parent answers (`tracker answer`) and the record comes back to you, or to the planner for a replan.
- Run each batch's "Done when" checks before `done`; `done` marks the batch's requirements implemented with your summary.
- Gaps you worked around anyway (a trivial missing import) go in your report so the planner learns.

## 4. Verification and handoff

1. Write the `done` summary as the implementation evidence: what you built and where (files, symbols).
2. Run formatting, generation, static analysis, architecture checks, and the unit and integration tests for what you changed (focused: the packages and pages your batch touches; the tester runs the full suite once), and name them in your `done` summary. Work and run commands only in the brief's `Worktree:` checkout; never edit `<repo>/main`, and never start the server against the dev database (use the isolated environment). Run independent checks at the same time:
   - use the project's parallel runner (`test.runner`) or background commands;
   - start the slow suites (e2e, audits) first, and do the quick checks while they run.

   New tests must be parallel-safe: isolated per worker and independent of order. Mark a test serial only with a one-line reason.
3. A check that applies but you could not run: `done --not-run "<check>: <why>"`. It doesn't block review or test handoffs, but it blocks acceptance until it runs or the user waives it. Use `not_applicable` (with the reason) only for a check that does not apply.
4. Run the inspection CLI's `check all` (if it has none, record it as `not_applicable`). A violation is a bug to fix or report, never something to ignore.
5. Run `spec-check`. Inspect the diff for unrelated edits, leaked secrets, generated-file drift, and boundary violations. Then clean it before review: `deslop` (narrating comments, speculative guards, dead code, duplicate helpers) and `no-comments` (a fresh comment reviewer), and rerun the focused tests.
6. `done "<what you built>"`: after the last batch it commits, checks for conflicts with main, runs the fast CI tier, and starts review and test; a refusal keeps the work with you (fix what it names, then `done` again). Use `ask` when blocked by a question, `blocked` for a spec problem.

## Planner role

Load this skill for its boundaries, then follow the planner agent and [references/planning.md](references/planning.md): plan template, mandatory checks (dependency trace, risks as steps, read-time fallbacks over rewrites, facts verified by command), and batching rules (every batch carries a `**Requires:**` line; independent batches first). The planner edits nothing; it stores the plan with `tracker plan add <feature> --from -`.

## Fixer role

When assigned as fixer:

- Fix only the parent-assigned bug IDs and the regressions they need.
- Reproduce each bug from its recorded steps before changing code. Use `tdd` when a cheap focused test path exists: the failing test first, then the fix. For a code-review finding with no runtime reproduction, first write a test that fails because of the defect.
- Fix the root cause, not the place it surfaced (`fix-root-causes`); look for the same fault elsewhere in your lane and fix every instance. When two fixes resting on one belief fail, test the belief before a third (`attack-the-premise`).
- Add a regression test that fails without the fix. Record `fixed <BUG-ID> "<how>" --test "<that test>"`.
- Never verify your own fix.
- Run the relevant checks, then `done "<what you fixed>"`: it opens the PR, and the tracker chooses a full re-verify or (a small low-severity fix touching nothing sensitive) a light one straight to retest.
- A stack E2E (anything that starts the shared stack) runs through `stack -- <command>`, so it never overlaps a tester's run.
- A merge-conflict or merge-queue CI bug: in your worktree, `git merge <main>`, resolve, rerun the focused tests, record the resolution as the fix, then `done`. Name the resolved files in your report: a fresh focused review checks them.

## Completion report

Return to the parent: implemented requirements and key files; checks run with results; checks not run and why; diagnostics and toolkit tools added, updated, or exercised; missing requirements, blockers, and dependencies; optional improvements skipped; confirmation that `specs/` is unchanged; record status and next role.
