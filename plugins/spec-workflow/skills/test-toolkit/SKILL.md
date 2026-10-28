---
name: test-toolkit
description: Define, build, and maintain a project's durable test toolkit (implementation/toolkit.json) - project-owned tools for state inspection, seeding, fault injection, external-service mocks, frontend driving and inspection, and environment isolation - plus the tool-gap loop that fills missing test capabilities instead of letting agents write throwaway scripts. Use when testing or reviewing needs a capability the project lacks, when acting as the toolsmith, when a feature changes state, UI flows, or integrations that tools depend on, or when bootstrapping a project.
---

# Test Toolkit

Testers can only test what they can drive and observe. When a capability is missing, the gap is recorded and a toolsmith builds a durable, project-owned tool, registered in `implementation/toolkit.json`, so the next run already has it. Without this loop, testers rebuild throwaway tools every round (m33: 58 scratchpad scripts in 7 runs; mock OAuth server, mock MCP server, Playwright drivers, `go -overlay` DB planting, seed scripts; see [references/examples.md](references/examples.md)).

The developer inspection CLI (`dev-inspection`) is the toolkit's `be.inspect` tool. Its rules still apply to it.

## Capabilities

| Capability | Provides |
|---|---|
| `be.inspect` | Read-only state snapshots and invariant checks (`dev-inspection`) |
| `be.seed` | Plant users, agents, chats, credentials, or edge-case rows deterministically |
| `be.fault` | Crash/kill a process, shift the clock, force deadlines and dependency failures |
| `be.concurrency` | Run multiple backend instances; race identical requests |
| `ext.mock.<service>` | Deterministic local fake of an external service (`ext.mock.oauth`, `ext.mock.mcp`, `ext.mock.chatgpt`), with scripted error modes and a request log |
| `fe.drive` | Programmatic UI: session, login, goto, click/fill by role and name, wait |
| `fe.inspect` | Snapshot: pruned a11y tree, scroll containers, overflow offenders, focus, console errors, failed requests, visual diff |
| `fe.audit` | Layout, a11y, and link audits over pages |
| `env.isolate` | Private copies, free ports, throwaway test databases |
| `data.cleanup` | Idempotent removal of everything a test created |

Frontend driver design: [references/fe-driver.md](references/fe-driver.md).

## Manifest (CLI only)

```bash
tracker toolkit list [--capability fe.drive]      # stale = never verified, failed, or changed since last pass
tracker toolkit summary                            # one line per tool, for delegation prompts
tracker toolkit add <name> --capability C [--capability C2] --command "<invocation>" --location <path> \
  --smoke "<command>" --owner-spec <id> --mode read-only|mutating [--guard "<dev-DB refusal>"] [--description "..."]
tracker toolkit update <name> [any add option]     # marks it stale until verify passes
tracker toolkit verify [<name> ...]                # runs smoke commands from the project root; fails if any fails
tracker toolkit remove <name> --reason "..."
```

`--location` is project-relative and must exist: `be/cmd/<tool>`, `fe/tools/<tool>`, or `tools/<tool>`; never `/tmp`, a scratchpad, `specs/`, or `implementation/`. A hook blocks direct edits to `toolkit.json`.

## Tool rules

- **Deterministic**: same inputs and fixture, same output. Pin clocks, seeds, IDs, and ports where the output depends on them.
- **JSON output**, bounded (default limits, truncation markers), compact enough for an agent's context.
- **Never print secrets** (except the dev-only inspection CLI under its own guard). Mock credentials are fixed test values.
- **Read-only or mutating, explicitly** (`--mode`). A mutating tool refuses the dev database and shared data unless the target is named explicitly (`--target`) and is a test target; it records that guard with `--guard`.
- **Idempotent cleanup**: everything a tool creates is tagged and removable by `data.cleanup`, twice in a row without error.
- **Self-describing**: `--help` lists commands; errors are JSON with stable codes and non-zero exits.
- **Smoke test**: a fast command that proves the tool works against the current code (start, one call, stop). `toolkit verify` runs it; only a passing tool can resolve a gap.

## Testability requirements come first

Since 0.7.1 a feature spec's `## Testability` section names the inspect commands, drivers, faults, mocks, and environment support it needs ([write-specs template](../write-specs/references/testability.md)). The executor builds them with the feature, as reusable generic commands (subcommands, flags, JSON, `--help`), registered with smoke tests. They are never one-off scripts or test procedures. Tool gaps cover only what review or testing finds missing later.

## Tool gaps

Tester or reviewer, before writing any helper:

1. Map each requirement to the capabilities it needs (happy path, edge cases, failures, UI, external services).
2. `tracker toolkit list` and use what exists.
3. For each missing capability: `tracker tool-gap add <feature> --capability <c> --requirement REQ-x [--requirement REQ-y] --why "<what cannot be tested>"`. Keep testing everything else, then hand off to the parent.

A tiny one-off probe (a single `curl`, a few lines of inline script) is fine. Anything reused, or longer than about 30 lines, is a gap, not a scratchpad script.

Open gaps block handoff to the tester and the acceptance gate. The parent hands off to the toolsmith, which resolves each gap with a verified tool (`tracker tool-gap resolve GAP-<feature>-NNN --tool <name> --evidence "..."`), then the tester resumes. The parent may instead defer a gap with a recorded user decision (`tool-gap defer ... --reason --user-decision --parent-confirmed`), like a waiver. `tracker tool-gap list [<feature>] [--open]` shows them.

## Maintenance

- A feature that changes persisted or runtime state, UI flows, routes or accessible names, or external integrations updates the affected tools and their smoke tests in the same work (`toolkit update`, `toolkit verify`).
- The orchestrator runs `toolkit verify` in preflight; a failing tool is fixed before delegation, like a broken toolchain.
- Promote: the same probe needed twice becomes a tool (`workflow-retro` reports scripts written outside the project as `tools.adhoc`).
