---
name: dev-inspection
description: Define, build, and maintain a project's developer inspection CLI. It is a strictly deterministic, read-only tool with unrestricted ("God mode") access to every datastore, service, and pipeline, giving agents bounded, structured snapshots and invariant checks (orphan rows, stuck jobs, state contradictions). Use when bootstrapping a project, when a feature adds or changes persisted or runtime state, when the same ad hoc query is needed twice, or to verify that a subsystem really works.
---

# Developer Inspection CLI

Agents debug by guessing unless they can *see* the system. This skill makes every project ship a development-only CLI that answers "what is the real state right now?" deterministically, so the agent, the reviewer, and the tester verify against facts instead of logs or assumptions.

The tool exists from the first commit and grows with every feature. It is never deployed. It is the `be.inspect` tool of the project's test toolkit (`test-toolkit`): register it in `implementation/toolkit.json` with a smoke command such as `inspect overview --json`.

## Principles

1. **Read-only, mechanically.** Every datastore session is read-only: a read-only transaction or role for SQL, `GET`/`HEAD` only for HTTP, peek-never-consume for queues, list/stat for object storage. No command repairs, retries, requeues, migrates, seeds, or deletes anything, ever. If a fix is needed, the CLI shows the problem and the application code fixes it.
2. **God-mode reads.** Bypass API authentication and tenant scoping. Connect directly to each store with development credentials, so inspection works when the API is down. Every value is shown as stored, secrets included. Never add redaction.
3. **Development targets only.** Secrets are printed in plain text and output ends up in agent transcripts, so the CLI must refuse every target not explicitly marked as development: a required environment marker plus a host allowlist. It must fail closed. This guard is the CLI's only security boundary, and it is not optional.
4. **Deterministic, as the primary objective.** The `data` part of the output is a pure function of (store state, `as_of`, arguments). The same inputs give byte-identical output on any machine. See [Determinism contract](#determinism-contract); it overrides convenience everywhere.
5. **Bounded.** Default and maximum list sizes, a byte cap per invocation, opaque pagination cursors, explicit truncation markers, and drill-down for large content. One call never floods the context.
6. **Agent-first output.** One versioned JSON document per invocation; text mode for humans; stable error codes; distinct exit statuses.
7. **Same meanings as the application.** Reuse the application's schema, domain types, enums, and config loading. Never re-describe a contract in the CLI. Load only the config the selected command needs, so unrelated broken config doesn't block inspection.
8. **Self-describing.** `inspect commands --json` lists every command and check with its purpose, filters, and output shape, so an agent can discover the tool without reading its source.

## Determinism contract

`data` is a pure function of (store state, `as_of`, arguments): `as_of` is the only clock, one consistent snapshot per invocation, total ordering ending in a unique key, no sampling or estimates, canonical JSON, volatile values only in `meta`/`observed`, no side effects on inspected state. Proven by a determinism test (twice, same fixture and `--as-of`, varied `TZ`/`LANG`/terminal: byte-identical `data`) and golden files. Full rules: [references/determinism.md](references/determinism.md). Load it when building or reviewing commands or checks.

## Command families

`overview`, resource `list`/`get`, process drill-down, `pipeline`, `services`, `check`, `snapshot <area>`, `config`, `sql` (read-only, bounded). Build those that apply; see [references/command-families.md](references/command-families.md).

## Invariant checks

Checks are the most valuable part of the tool: they turn "I think it works" into a deterministic yes or no. Keep them in one declarative registry:

```text
id: orphan.chat-without-agent        # stable, dotted: <category>.<name>
severity: critical|high|medium|low   # same scale as spec-tracker
description: Chats whose agent row no longer exists
query: <read-only query or probe>
result: violation count + bounded sample of offending IDs
```

`check all` runs every check and is mandatory from the first commit (an empty registry reports zero checks and exits 0). `check <id|category>` runs a subset. Any violation exits with the unhealthy status, so checks also work as a test oracle. A check is deterministic like every other command: its thresholds come from configuration plus `as_of`, and its sample is the first N violations in a defined order. Write a check whenever a spec states an invariant the database cannot enforce by itself. See [references/check-catalog.md](references/check-catalog.md) for categories to cover.

## Lifecycle

1. **Define (once, at project start).** Create a `convention` spec (`spec new --kind convention --title "Developer inspection CLI"`) from [references/spec-template.md](references/spec-template.md), through the `write-specs` workflow. The user confirms language, location, targets, and dev-target markers. Record the plaintext-secret output as an accepted risk in a `decision` spec. Later changes to the CLI contract are new specs that amend it. Build the CLI shell, dev-target guard, `overview`, `commands`, `config`, and `sql` with the first (bootstrap) spec.
2. **Grow with every feature.** A feature that adds or changes persisted or runtime state adds or updates, in the same work:
   - `list`/`get` or drill-down commands for its new state;
   - checks for each invariant its spec states (ownership, references, state and timestamp consistency, lifecycle terminals);
   - the suspicious-state categories for its failure paths (stuck, expired, past deadline).

   The feature isn't done until those commands have been run against real data.
3. **Promote ad hoc queries.** If you run the same `sql` query or manual probe twice, turn it into a structured command or check.
4. **Never regress.** Keep commands for every feature that still exists, so later work can re-verify earlier features and cross-feature relationships. A breaking JSON change bumps the schema version.
5. **Test the tool.** Each command and check has a test against a fixture database. Checks need both a passing fixture and a violating one. Tests also cover the dev-target guard refusing a non-dev target, and the guarantee that no mutation is possible.

## Using it

- Run `overview` and `check all` before starting work and before handing off. A failing check is either a bug in the work or a pre-existing one; report it either way.
- If a project's inspection CLI has no `check all` (a legacy CLI), record `check add --name inspect-check-all --result not_applicable --evidence "<reason>"` instead of `not_run`, and report the gap; adding it is a convention amendment for the user to approve.
- Verify a change by taking `snapshot <area>` before and after the action and diffing the `data`. Pin `--as-of` when comparing time-dependent results. If two snapshots of an unchanged system differ, that is a determinism bug in the CLI; fix it before trusting any diff.
- Use structured commands over `sql`, and `sql` over guessing.
- In the spec workflow: the implementer adds commands and checks, the reviewer verifies they exist and match the spec's invariants, and the tester records their output as evidence.

## Definition of done (per feature)

- [ ] New persisted or runtime state is visible through a structured command.
- [ ] Every invariant in the spec has a check, with passing and violating fixture tests.
- [ ] Failure paths have suspicious-state categories.
- [ ] `inspect commands` lists the additions.
- [ ] Commands and checks were run against real development data, and their output was recorded as evidence.
- [ ] New commands and checks pass the determinism test (same fixture and `as_of` give byte-identical `data` across environments) and are covered by golden files.
- [ ] No mutation path exists, and the dev-target guard still fails closed.
