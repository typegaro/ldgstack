# Delegation Prompt Template

`tracker brief <feature> --role <role> [--batch N|REQ-a..REQ-b] [--final-batch]` fills this template from the record, `implementation/preflight.json`, the toolkit, and the role's active assignment. Paste its output verbatim (never a pointer such as "run brief" or a file path) and append extra context only below it. Never include another agent's report or rationale for a reviewer or tester. Placeholders are `{name}`; the CLI refuses to render when a value is missing and says which command supplies it.

```text
{marker}
Spec: {spec_path} (effective text: {spec_cli} show {spec_id} --effective)
Role: {role}
Feature: {feature}
Status: {status} (current role: {current_role})
Scope: {scope}
Plan: {plan}
Decisions: {decisions}
Assignment: {assignment}
First command: {claim_command}
Ownership: {ownership}
Toolchain (verified by preflight; use exactly):
{toolchain}
  tracker: {tracker}
Toolkit (stale tools marked):
{toolkit}
Open tool gaps: {gaps}
Next command: {next_command}
Efficiency:
  - A read-only turn contains every read you already know you need; issue a single read only when its result decides the next.
  - Locate with grep -n, then read one bounded range; after an edit, re-read only the edited range.
  - Use the toolchain lines above as given; run `--help` once before any other unfamiliar command.
  - Write only inside Ownership; the hook denies other paths. Scratch files go in your scratchpad, never the project.
  - Tester/reviewer: use toolkit tools; record a tool gap instead of writing a throwaway script (>~30 lines or reused).
  - Fixer: load dev-inspection only if the bugs touch persisted or runtime state.
  - Executor: follow the plan literally; if it is wrong or missing a file, stop with `handoff --to parent --question "..."` instead of improvising.
  - Final message: under 300 words; the record holds the details.
```
