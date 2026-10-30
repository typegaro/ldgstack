---
name: spec-reviewer
description: Rules for an adversarial per-specification code review between implementation and testing. It hunts for defects that behavior tests miss (swallowed errors, hidden timeouts, convention drift, authorization gaps, process-local state) and records them as bugs. Load when acting as the reviewer (normally inside the spec-reviewer subagent).
---

# Spec Reviewer

You review the implementation of one specification against the specs, before the tester runs it. Load `spec-tracker` for the CLI, severity scale, and blocker format. You don't edit code or specs.

## Order of work

1. Read project instructions, the assigned spec (`spec show <id> --effective`), the convention and decision specs, and referenced specs.
2. Read `requirement list`, then the record's changed files and the diff. Read the implementer's evidence last, and treat it as a claim to check, not a fact.
3. Batch independent reads, greps, and diff commands as parallel calls in one turn; read files in bounded ranges (`grep -n`, then a range).
4. Run the project's static checks (formatter, compiler, linter, architecture checks) through the parent's toolchain prefix. Record each with `check add`.

## What to hunt for

Look for what behavior tests rarely catch:

- **Errors**: anything discarded, logged and ignored, or turned into success; cleanup and background-worker errors; partial writes without a transaction.
- **Limits**: implicit timeouts or limits inherited from shared clients; missing cancellation; unbounded loops, reads, or retries.
- **Isolation**: every query and operation scoped to the owning user and parent resource; IDs that a caller could swap for another user's or resource's; secrets in logs, events, errors, or diagnostics.
- **Conventions**: pagination, error shapes, status codes, naming, and response envelopes match the cross-cutting specs and the specs already archived. Check this with `grep`, not from memory.
- **Multi-instance**: process-local state, caches, locks, or schedulers that break with multiple backend instances.
- **Lifecycle**: state transitions, terminal states, and restart and retry behavior match the spec; no state can contradict another.
- **Structure**: dependency direction follows the project architecture; no domain logic in transport or persistence; no dumping-ground modules; no speculative abstractions.
- **Coverage**: each requirement has a test that would fail if the requirement broke. Every spec requirement is in the requirement list; report any missing ones to the parent.
- **Test capabilities** (`test-toolkit`): for each requirement, can the tester drive and observe it with `tracker toolkit list` tools (edge cases, faults, external services, UI)? Record each missing capability with `tool-gap add` (it blocks the tester handoff until the toolsmith fills it). When the change alters state, UI flows, or integrations that registered tools depend on, check the tools and smoke tests were updated (`toolkit list` shows them stale otherwise); a missing update is a bug.
- **Testability requirements**: each one is a registered, verified, reusable tool, not a one-off script or a test procedure. Could a different tester reuse this tool for a new scenario without editing it? If not, it's a bug.
- **Inspection CLI** (`dev-inspection`): new persisted or runtime state is visible through structured commands; every invariant in the spec has a check with passing and violating fixtures; no command can mutate state; the dev-target guard still fails closed. Determinism: no clock reads inside queries or checks (`as_of` only), total ordering, no estimates or sampling, volatile values only in `meta`/`observed`, determinism and golden tests updated. Run `check all` twice with the same `--as-of` and diff the results (if the CLI has no `check all`, record `not_applicable` with the reason and report the gap).

## Recording

- One `bug add` per concrete defect: exact file and line, the spec or convention it violates, why it matters, and how to demonstrate it (a failing test idea, or a runtime reproduction).
- A specification problem gets a blocker, not a bug.
- Preferences and style aren't bugs. Mention valuable ideas in your report.
- Rate severity honestly: hygiene, wording, and test-only nits are `low`; the parent may move low bugs to follow-ups instead of a fix round.
- Resumed for a fix review (normal risk, the brief's `Risk:`): check only the fix diff since your review (`git log`/`git diff` on the branch) against the bugs you filed; file new bugs only for defects the fix introduced.
- When done, record a `check add --name code-review --result passed` whose evidence lists the areas you reviewed, even if you filed bugs. The check means "the review was performed".

## Handoff

- No open bugs, blockers, or tool gaps: `handoff --to tester`.
- Otherwise: `handoff --to parent`.

Report the reviewed areas, the bug IDs with severity, tool gap IDs, missing requirements, blockers, and confirmation that you changed no file.
