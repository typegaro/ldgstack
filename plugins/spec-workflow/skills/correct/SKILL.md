---
name: correct
description: Stop repeating the same correction to agents - mine recent commits, reverts, review findings, bug records, retro reports, and agent instruction files for mistake classes that happened twice, fix each at the highest level that works (architecture, then types, lint, CI or a tracker/hook gate, then tests, prose last), prove each new check fails on a real past mistake, and keep a table pairing every rule with what enforces it. Use for "/correct", after a retro, or when the same feedback recurs.
---

# Correct

Assume every contributor is an agent that sees only the files it opened, copies the nearest example, and takes the shortest path that compiles. Change the repo so a change that looks right from one file is right for the whole repo.

## Find the mistake classes

Read recent commits and reverts, bug records (`implementation/active` and `archive`: `found_by`, `fix`, repeated titles), `tracker follow-ups`, workflow-retro reports, review findings, the agent instruction files (CLAUDE.md, AGENTS.md, skills), and comments explaining workarounds. Group mistakes into classes. A class counts once it happened twice.

## Fix each class at the highest level that works

1. **Architecture removes it.** One owner per piece of state, one supported way per task, internals the wrong caller can't import, one source of truth instead of hand-synced lists, old ways deleted so nobody copies them.
2. **Types or checks reject it.** If bad code still compiles, add a lint rule, CI check, pre-commit or path-guard hook, or tracker gate whose error names what to do instead. When the pattern is already common, fail only on new instances.
3. **Tests catch it.** Fix tests that pass when the behavior breaks or fail when only internals change (`test-behavior`).
4. **Prose last**, for judgment calls only. Nothing fails when an agent skips a sentence.

## Fix and prove

Fix the most frequent classes now, one commit each. Prove each new check fails on a real past mistake (check out the old commit or replay the bad diff). Run the same command locally and in CI. Exceptions sit on the offending line with a reason, an expiry, and the user's approval.

## Keep the rule table

In the project's agent instruction file, keep a table: rule, what enforces it (the check, hook, gate, test, or "prose only"), and the mistake that motivated it. When the user corrects an agent: fix the mistake and add the rule. If the rule was already there with nothing enforcing it, that is a repeat: enforce it at the highest level in the same change. Drop a rule once its mistake can no longer happen.

In the spec-workflow plugin itself, the same rule applies: a repeated agent failure becomes a tracker refusal, gate, or hook rather than more skill text.

**Report**: each class with its evidence, the level chosen and why a higher level didn't work, the proof that the check fails on the past mistake, and the updated rule table.
