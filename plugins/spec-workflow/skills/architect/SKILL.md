---
name: architect
description: Settle the shape of code before writing it - ground in the subsystem with how (and why), sketch at least two structurally different designs as types, signatures, and module boundaries with not-implemented bodies via arena, screen them for design red flags, pick by interface depth, then implement against the sketch and scrap it when friction shows it is wrong. Use for code that crosses a function boundary, one-way-door designs, high-risk specs, or "/architect".
---

# Architect

## Ground

Run `how` over every system the new code touches; naming a file isn't grounding. When the design changes ownership or layering, run `why` on the current shape so its reasons become constraints. Skip only for true greenfield code.

## Sketch twice

Write the caller's usage first, then derive types and signatures from it. Run `arena` with at least two structurally different candidates (whole shapes, not variations inside one shape). Each candidate is types, function signatures, module boundaries, and `not implemented` bodies with pseudocode.

Screen every candidate for red flags before choosing:

- A caller must know the abstraction's internal rules to use it.
- Pass-through layers or interfaces with one implementation.
- Optional fields that are always set in practice, or casts and escape hatches to compile.
- State shared between actors where the design said it wasn't.
- The same special case handled in several places.
- A change that looks right from one file but is wrong for the repo (agents copy the nearest example).

Prefer the deeper interface: the most complexity hidden behind the smallest public surface.

## Decide

By default, continue straight to implementation. Stop for sign-off only when asked ("with checkpoint"). In a spec run the planner puts the chosen sketch and the rejected alternative (one line each) into the plan.

## Implement against the sketch

Replace `not implemented` bodies. The sketch is the contract: a deviation (a parameter it didn't anticipate) is a signal to raise in the handoff, not friction to absorb silently.

## Scrap when it's wrong

Throw the sketch away when the same workaround keeps appearing, unrelated edge cases each need a branch, types need escape hatches, a lock appears where no state was supposed to be shared, or two independent deviations have the same shape. Rerun `how`, redesign as if the new constraints were day-one (`redesign-not-bolt-on`), make the new sketch smaller first (`subtract-first`), and arena again.
