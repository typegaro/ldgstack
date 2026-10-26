# Testability section (from 0.7.1)

A `feature` or `change` spec that adds or changes persisted or runtime state, a UI flow, or an external integration ends with `## Testability`. Its requirements are ordinary `- **R<n>** [ops]` bullets. They are built, reviewed, and tested with the feature in the same spec, not later through tool gaps. `spec validate` warns about a missing section, and makes it an error for specs created by 0.7.1 or later (`workflow:` in the frontmatter), or for every spec with `--strict-testability`.

A spec with no state, UI flow, or integration (pure docs, a rename) writes `Not applicable: <reason>` under the heading. `decision`, `convention`, and `removal` specs are exempt.

## Reusable tools, not test procedures

Every tool a Testability requirement names must be:

- **Durable and generic**: a command with subcommands and flags and JSON output that works for any future resource or scenario of the feature. It is not hardcoded to one test case, fixture, or ID.
- **Registered** in `implementation/toolkit.json` (`toolkit add|update`) with a smoke test that `toolkit verify` passes.
- **Documented** with `--help`, which lists every subcommand and flag.
- **Maintained**: a later spec that changes the feature updates the tool and its smoke test.

One-off scripts, ad hoc test procedures, and scenario-specific programs don't satisfy a Testability requirement. Tests may call the tools, but each tool must stand on its own. Ask: could a different tester reuse this tool for a new scenario without editing it?

## Template

```markdown
## Testability

- **R<n>** [ops] Inspection: `inspect <family> <command> [--flags]` shows <fields added or changed>. It is read-only, bounded, and deterministic, with secrets and the dev-target guard per dev-inspection, and `inspect check all` gains `<invariant>`.
- **R<n>** [ops] Drivers: `<tool> <subcommand> [--flags]` creates and drives <resource> through <states> without the UI or the model, for any <resource>, with JSON output and `--help`.
- **R<n>** [ops] Fault and mocks: `<tool> <fault> --target <id>` injects <failure>; `ext.mock.<service>` serves scripted <error modes> with a request log.
- **R<n>** [ops] Environment: `env.isolate` gives <what: a private database, ports, a container runtime>; each tool is registered in the toolkit with a smoke test.
- **R<n>** [ops] Verification: <scenario> → <tool or test>; <failure path from R<x>> → <fault + inspect command>; <UI flow> → `fe.drive` + `fe.inspect`.
```

Leave a line out only when it doesn't apply (no external service means no mock line). Every new state, flow, and integration, and every failure path the requirements name, appears in Verification.

## Example (compute leases)

```markdown
## Testability

- **R14** [ops] Inspection: `inspect compute leases [--agent ID] [--state S] [--limit N]` lists lease id, agent, state, provider, deadline, and last heartbeat, newest first, bounded to 50. `inspect compute lease <id>` adds the transition history. `inspect check all` gains `compute.expired-active` (an active lease past its deadline).
- **R15** [ops] Drivers: `compute-drive lease create|heartbeat|release|show --agent ID [--target test-db]` drives any lease through its lifecycle without an agent run, with JSON output, `--help`, and a refusal to touch the dev database unless `--target` names a test target.
- **R16** [ops] Fault and mocks: `compute-fault provider-down|slow-start|crash --lease ID` makes the fake provider adapter fail the next call to that lease, and `compute-fault clear` removes every injected fault.
- **R17** [ops] Environment: `env.isolate` provides a throwaway database and the fake provider adapter. `compute-drive` and `compute-fault` are registered in the toolkit (`be.seed`, `be.fault`) with smoke tests.
- **R18** [ops] Verification: create → heartbeat → release (R3–R5) with `compute-drive` + `inspect compute lease`; a timeout (R7) with `compute-fault slow-start` + `inspect check all`; a provider crash and cleanup (R8) with `compute-fault crash` + `inspect compute leases --state failed`.
```
