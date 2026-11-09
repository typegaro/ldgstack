---
name: spec-tracker
description: How agents work with the implementation-record tracker - start with the brief's claim, then use your assignment's few verbs (done, bug, fixed, tested, retest, ask, blocked, gap, stack) - plus the severity scale and blocker format. Load whenever acting as planner, implementer, fixer, reviewer, tester, or toolsmith on a specification.
---

# Spec tracker (for agents)

The tracker holds every spec's state; you never edit `implementation/` by hand. Your brief gives the exact command prefix and your assignment ID. Every command you need is `<tracker> <ASSIGNMENT> <verb> ...`: the assignment names your spec and your role, so you never pass a feature name, a role, or a `--parent-confirmed`.

1. First command: `<tracker> claim <ASSIGNMENT>` (binds you to your assignment).
2. Work.
3. Last command: `<tracker> <ASSIGNMENT> done "<what you did>"`.

## Verbs

| Verb | Who | What it does |
|---|---|---|
| `done "<summary>"` | everyone | Ends your round. Implementer: marks your batch's requirements; after the last batch it commits, runs fast CI, and starts review and test (a CI failure keeps the work with you: fix and run `done` again). Fixer: the same, and the tracker picks a full or a light re-verify. Reviewer and tester: records your round and hands the spec back. Add `--not-run "<check>: <why>"` for a check that applies but couldn't run. |
| `bug "<title>" --repro "<command>" --got "<output>"` | reviewer, tester | A bug you reproduced; it blocks the merge. Options: `--severity low\|medium\|high\|critical` (default medium), `--expected "..."`, `--spec-ref R3`, `--unproven` (found by reading; low and medium become follow-ups), `--preexisting` (main already has it). |
| `fixed <BUG-ID> "<how>" --test "<regression test>"` | fixer | One assigned bug is fixed. |
| `tested REQ-n\|all "<what you observed>"` | tester | A requirement observed working. |
| `retest <BUG-ID> ok\|fail "<what you saw>"` | tester | A fixed bug's retest. |
| `ask "<question>"` | everyone | Stops you and asks the parent; it answers and resumes you. Use it instead of guessing. |
| `blocked "<why>"` | everyone | The spec is contradictory or unsafe (blocker format below). |
| `gap <capability> "<why>"` | tester, reviewer | The toolkit can't drive or observe something (`test-toolkit` capabilities); don't write a throwaway script. |
| `stack -- <command>` | writers | Runs a command that starts the shared test stack, waiting for a free test slot. |

The planner stores its plan with `<tracker> plan add <feature> --from - <<'PLAN' ... PLAN`, then `done`. The toolsmith registers tools with `<tracker> toolkit add|update|verify ...`, then `done`. Read-only views anyone may run: `<tracker> status <feature>`, `<tracker> requirement list <feature>`, `<tracker> plan show <feature>`, `<tracker> toolkit list`.

An error names what to do instead. Follow it rather than retrying the same command.

## Severity

- `critical`: data loss, security or isolation breach, corruption, or the core flow is unusable.
- `high`: a requirement fails, or a major path is broken without a workaround.
- `medium`: a requirement partly fails, or an edge case is wrong, with a workaround.
- `low`: hygiene, wording, or test-only issues that don't change required behavior.

## Blocker format

For `blocked`: the specs involved (path and section), the exact conflict or missing decision, why you can't proceed safely, the options with their trade-offs, and your recommendation.

## Gates (for reference)

A spec merges only when every requirement is implemented and tested, no bug or tool gap is open, no check failed or wasn't run, a passing review and a passing test cover the exact patch that lands, and fast CI passes on the merged result. The parent and the tracker handle the rest; the [full reference](references/full-reference.md) lists every underlying command.
