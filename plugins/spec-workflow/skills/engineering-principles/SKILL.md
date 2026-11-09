---
name: engineering-principles
description: Named engineering principles that briefs, reviews, and handoffs cite by name (e.g. "fix-root-causes", "test-behavior"). Covers deletion bias, data shape first, root causes, boundaries, types, idempotence, shared state, verification, measurement, and delegation. Load when implementing, fixing, planning, reviewing, or when a brief or review cites a principle.
---

# Engineering principles

Each principle has a name you can cite in a handoff, a bug, or a review ("fix-root-causes: the guard hides why the row is missing"). Cite only the ones that changed a decision, and say which decision. None of them is a line-count target: a smaller diff is good when it solves the problem, never a gate on its own.

## Core

- **smallest-change.** Solve the problem with the least new surface. Prefer deletion to addition, one source of truth to a decision repeated in several places, and no layer, flag, or abstraction the requirement does not need.
- **data-shape-first.** Before writing logic, name the core types and data structures and trace how every caller reads them. Get the shape right and the code that uses it becomes obvious. Ask what concurrent actors share before they share it.
- **redesign-not-bolt-on.** When a new requirement lands in an existing design, ask what you would build if it had been a day-one requirement, then move toward that. Update every type, doc, and example it touches.
- **attack-the-premise.** When two fixes that rest on the same belief fail the same check, write the belief down and test it directly before a third fix.
- **subtract-first.** Remove dead code, redundant validators, and stale references before you build on top. Leave the area simpler than you found it.
- **reader-load.** Count the hops between a question and its answer, and the hidden state a reader must hold. Inline one-caller wrappers and pass-through layers; prefer pure functions and local state.
- **end-state-first.** In a planned migration, converge on the target design. Don't keep temporary compatibility code alive to make every intermediate step smooth; declare where breakage is allowed and verify fully at the end.
- **experience-first.** When implementation convenience fights the user's (or the next maintainer's) experience, pick the experience. Fewer, finished features beat more rough ones.
- **compare-designs.** For a decision with no precedent, build two or three competing sketches and compare them before committing (see the `prototype` and `architect` skills).
- **build-the-lever.** For non-trivial work, write the script, codemod, generator, or check that does or proves it, so a reviewer reruns it instead of trusting you. Do one unit by hand first to learn the recipe.

## Architecture

- **model-the-domain.** Encode the domain in a structure (state machine, typed model, table, registry, reducer) instead of booleans and branches spread across files. A new feature that adds one more `else if` is the sign you skipped it.
- **boundary-discipline.** Validate and parse at system boundaries (HTTP, CLI, config, queues, external APIs, database rows). Inside, trust the types. Keep business logic in pure functions and the framework shell thin.
- **type-discipline.** Make illegal states unrepresentable: distinct types for distinct IDs, parse untyped input into the domain model once, handle every variant exhaustively, derive types from the authoritative schema (migration, OpenAPI, proto) instead of hand-copying them.
- **idempotent-operations.** Every state change converges to the same end state however many times it runs or wherever the last run crashed. Derive the step from the current state; make leftovers (locks, temp files, claimed jobs) recognizable as stale.
- **migrate-then-delete.** When a new internal API replaces an old one, move every caller and delete the old one in the same change. No compatibility shim without an external user who needs it.
- **separate-shared-state.** Before two actors write the same file, row, key, or branch, ask whether they need to. Give each its own target and merge at read time; serialize structurally (one writer, a lock, a queue) only when one shared object is a real invariant.

## Verification

- **prove-it-works.** Check the real artifact: run the command, read the stored value, drive the UI, inspect the diff. "It compiles", a green build, or an agent's summary is not proof. When a check passes too easily, suspect the check.
- **fix-root-causes.** Trace a symptom to the first wrong decision and fix it there. A guard, retry, clamp, or swallowed error is a fix only when the state it handles is legitimate. Fix every instance of the pattern, not just the one that surfaced.
- **verifiable-units.** Break multi-step work into small units that each end in a passing check; don't start the next unit on a red one. Order commits so the story proves itself (the failing test, then the fix).
- **test-behavior.** A test asserts what a caller, user, or other service can observe. Judge it with two imagined edits: break the behavior (the test must fail) and restructure the internals without changing behavior (the test must still pass). Rewrite or delete tests that fail either edit.
- **explain-the-number.** Before you trust or report a measurement, name what limits it and rule out what else it could be measuring (errors, cached or skipped work, an untuned side, noise). See `benchmark-checklist`.

## Delegation

- **guard-the-context.** Send bulk reading and fan-out to subagents; keep summaries, not raw dumps, in the coordinating thread. Cap scope per agent.
- **never-block-on-the-human.** On reversible work, decide, act, and report the decision (in the tracker decision log when the parent decides alone). Ask the user only for irreversible actions and product or preference calls no experiment can settle.

## Meta

- **encode-lessons.** When you write the same instruction a second time, make it a check instead: a tracker gate, a lint, a test, a hook, a script. Prose is the last resort, for judgment calls. See the `correct` skill.
