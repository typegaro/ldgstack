# Planning (planner role)

A plan turns one spec into batches that an efficient execution model follows literally. In the m33 pilot (specs 0033/0034), every executor question came from a plan gap: missed files (an icons file, a migration version constant, loader code for a fallback), a known risk written as a note instead of a step, a backfill that rewrote immutable snapshots, and a wrong weekday. Close those gaps here.

## Mandatory checks (before writing the plan)

1. **Dependency trace, before the file list.** For every change, follow what must change with it: constants, registries, and version files (migration version, route/icon/tool registries, schema versions); loaders and queries that feed any new field or fallback; every implementation of an interface you change; generated code and its generator command.
2. **Every known risk that would break a requirement becomes a step** with a test, not a note. Example: "after a reload the tool count must stay N" is a step with an assertion.
3. **Prefer read-time fallbacks over data rewrites.** Never plan writes to rows a spec declares immutable (snapshots, audit records, accepted history). If only a rewrite works, raise a blocker.
4. **Verify facts with a command,** not from memory: dates and weekdays (`LC_ALL=C date -d 2026-10-25 +%A`), time zones, tool and library versions, counts, current constants. Put the command and its output in Findings.

## Template

`tracker plan add <feature> --from -` validates these headings: `## Ownership`, `## Findings`, `## Batch N: <title>` (numbered 1..N in order, each naming its `REQ-n` and a `**Requires:**` line), `## Stop conditions`, `## Out of scope`. Keep sub-structure in bold labels or bullets, not `##` headings, inside a batch.

```markdown
## Ownership
- `be/internal/chat/**`
- `fe/src/components/run-panel/**`

## Findings
- be/internal/chat/store.go:142 `loadRun` builds RunView; the new field needs its SELECT (line 118) too.
- Migration version constant: be/internal/db/migrate.go:12 (`LatestVersion = 33` → 34).
- `LC_ALL=C date -d 2026-10-25 +%A` → Sunday.

## Batch 1: <title, independently testable>
**Requirements:** REQ-001, REQ-002
**Requires:** none
**Files:** exact paths, each with what changes (new, edit at function X).
**Change shapes:** signatures, struct fields, SQL, and skeletons for anything non-obvious.
**Edge cases:** each one, with the behavior the spec requires.
**Tests:** file, test name, exact assertions (inputs → expected values or errors).
**Commands:** exact build, lint, and test commands with the toolchain prefix.
**Done when:** checklist, including `requirement implemented` for each ID and the `check add` names.

## Batch 2: ...

## Stop conditions
- Ask the parent (`handoff --to parent --question`) if: a listed file or symbol does not exist, a test cannot be written as specified, a step would touch a file outside Ownership, or the spec and plan disagree.

## Out of scope
- What the executor must not change, even if tempting (refactors, other specs' requirements).
```

## Ownership granularity

- Own feature code by its directory (`be/internal/chat/**`). Own shared test infrastructure and other hot shared directories (test support and fixtures, `fe/tools/lib`, request/API helpers, registries) by file or narrow subdirectory: `fe/tests/support/request.ts`, `fe/tests/e2e/chat/**`, never `fe/tests/**` or `fe/tools/**`. A coarse lane makes `assign` refuse every parallel spec that touches one shared helper (m33: the 0062 fixer had to send patches through the parent).
- List the exact shared files a batch edits under its `**Files:**`; `assign` then reports any overlap with another spec's lane precisely.

## Batches

- Write `**Requires:**` on every batch: `none` when it touches nothing a still-unaccepted dependency provides, else the spec IDs it needs accepted. A spec started early (`init --early`) runs only batches whose required specs are accepted; a batch without the line counts as requiring all of them. Put `none` batches first.
- Each batch builds, passes its tests, and leaves the tree consistent on its own. Order them so later batches only add.
- Put every requirement in exactly one batch. Keep batches small enough for one executor turn sequence (about 3–8 requirements, one or two areas).
- Name exact files and symbols. "Update the loader" is a gap; "`be/internal/chat/store.go` `loadRun`: add `subagent_count` to the SELECT and scan" is a step.
- Name the `check add` names the executor records, so retests can re-record the same names.

## Testability requirements (since 0.7.1)

- Requirements under the spec's `## Testability` (inspect commands, drivers, faults, mocks, environment support) are ordinary executor work. Plan them as normal batches, usually the last batch or inside the batch whose feature they exercise. Never route them to the toolsmith.
- Each tool is a reusable, generic command (subcommands, flags, JSON output, `--help`) in a toolkit location (`be/cmd/<tool>`, `fe/tools/<tool>`, `tools/<tool>`). It is never a one-off script or a fixture-bound test program. Tests may call it.
- The batch names the `toolkit add|update` command with its smoke test, `toolkit verify <name>`, and the `requirement implemented` evidence: `tool <name> (<invocation>); --help documents it; smoke: toolkit verify <name> passed`. The tracker rejects Testability evidence that names no verified tool.
- The toolsmith handles only gaps found later in review or testing (`tool-gap add`). If a toolkit requirement is already routed to the toolsmith, the parent records the gap with `tool-gap add --parent-confirmed`.

## Replanning

On `--replan` or a handoff back to the planner, the brief's scope shows the reason. Read `tracker plan show <feature>` and the record's questions, fix the gap at its root (usually a missed dependency), and store a new version. Keep batch numbers stable for batches already implemented.
