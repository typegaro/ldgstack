---
name: formal-verification
description: Prove one property that tests rarely reach - two retries that overlap, a lease that expires mid-write, out-of-order events, a state machine that can deadlock - with the tool that fits (a TLA+ model checker for orderings, a property or fuzz test against the real code for inputs), show the check failing on a broken variant, and leave a project-local recheck recipe that records which code it covers. Optionally draws a statechart of what the user sees. Use for high-risk concurrency, lifecycle, retry, lease, queue, or parser code, or "/formal-verification".
---

# Formal verification

## Pick the target

Choose a promise the code makes where a break hurts users and tests rarely reach the breaking case: "a job never runs twice at once", "a message is never delivered twice", "a chat never shows another user's data", "a lease holder always releases". Pick the strongest target, not the easiest. The user may name one.

## Pick the tool by the question

- **Can events happen in a bad order?** Model the design in TLA+ (or PlusCal) and check it with TLC: states, actions, the invariant, and fairness only where the real system has it. Keep the model small and name every action after the code path it mirrors.
- **Does the code behave for every input?** Property-based or fuzz tests against the real function (Go `testing.F`, `rapid`, fast-check). Don't hand-write a model of a function you can call.
- **Must it hold at every size?** A proof may be needed; say so and scope down to a bounded check instead of overclaiming.

Say which tool you chose and why.

## Prove the check can fail

Run the check on the real property and on a deliberately broken variant (remove the lock, reorder two steps, drop the idempotency key). A check you have never seen fail proves nothing. If the current code already breaks the property, report the counterexample as a short sequence of steps in the code's terms; don't change product code unless asked, and don't weaken the property.

## Leave the recheck recipe

Write `implementation/verification/formal/<property>.md` (or the project's chosen folder) with: the property in plain words, the model or test files, the one command that runs it, the bounds, which code it covers (paths) and the commit it last matched, and how to tell a real bug from a modeling error. Register the command as a toolkit tool with a smoke test. After refactors of the covered code, update the model from the code, rerun, prove the updated check still fails on a broken variant, and say for each failure whether it is drift in the model or a bug.

## Statechart (optional, for whoever owns the behavior)

When a product owner needs to see the behavior, generate a Mermaid state diagram of what the user sees from the checked model, mark each state that breaks a rule, and give the shortest path to it in the user's words. Reproduce each bad path in the real code before showing it, so a modeling error never reaches them as a bug.

## Report

What was verified, with which tool and bounds, the failing-variant evidence, what the check found, and what it does not cover. A pass covers the model or the bound, not the whole system.
