---
name: deslop
description: Clean AI slop out of a code diff before it is committed or handed to review - narrating comments, speculative guards and fallbacks, dead code, needless wrappers, defensive copies, debug leftovers, and duplicated helpers - without changing behavior. Use before every writer handoff (implementer, fixer), or when asked to "deslop" or tighten a diff.
---

# Deslop

Read your own diff (`git diff <base>...HEAD` in the spec checkout, plus uncommitted changes) as a reviewer who has to maintain it, and cut what does not earn its place. Behavior stays identical: rerun the focused tests afterwards.

## Cut

- Comments that narrate the code ("loop over users", "Phase 1", "call the API") or restate a name. Keep a comment only for a non-obvious why the code cannot show; `no-comments` runs the comment review.
- Guards for states that cannot happen inside a validated boundary (`boundary-discipline`), fallbacks nobody asked for, retries that hide errors, catch-and-continue blocks, `|| default` that masks a bug.
- Dead code: unused parameters, exports, branches, feature flags that are always on, commented-out code, TODOs without an owner.
- Wrappers and helpers with one caller that add no meaning; a new helper that duplicates an existing one (search before adding).
- Debug output, temporary logging, stray `console.log`/`fmt.Println`, skipped or focused tests.
- Over-general types and options added "for later" (`smallest-change`).
- Formatting churn and unrelated renames in files the change otherwise doesn't touch.

## Keep

- Error handling at real boundaries, with errors that say what to do.
- Anything the spec, a convention spec, or a project rule requires.
- Comments that cite an external constraint the code cannot express (a protocol, a vendor quirk, a security reason).

## Finish

Rerun the focused tests and the linters for the touched paths, commit the cleanup in the same round, and mention it in the handoff's `--completed` in one line.
