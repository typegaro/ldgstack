---
name: adversarial-spec-review
description: Adversarially review specifications in specs/ for contradictions, missing decisions, unsafe assumptions, abstraction leaks, and database, lifecycle, security, or multi-instance flaws. Use when reviewing specs, before finalizing any spec, or when auditing an implementation against its specs.
---

# Adversarial Specification Review

Use this skill when reviewing one or more specifications in `specs/`. Review the specifications as contracts that another engineer must be able to implement safely without guessing.

## Principles

1. Be adversarial toward the design, not the author.
2. Cite exact files and lines for every concrete finding.
3. Explain the impact, not only what is missing.
4. Distinguish contradictions and unsafe behavior from optional improvements.
5. Do not invent product requirements. Identify unresolved decisions and ask for them.
6. Prioritize correctness, security, ownership, lifecycle, and implementability over wording or style.
7. Do not edit specifications unless the user explicitly requests changes. Before editing, load and follow the `write-specs` skill.
8. Apply the same review standard to MVP and production specifications. Do not suppress, downgrade, or omit a finding because the project is an MVP.
9. Report all questions needed to resolve material ambiguity. Group and deduplicate them, but do not impose an arbitrary question limit.

## Review Workflow

### 1. Establish scope

- Read all requested specifications and governing repository instructions.
- Identify referenced specifications, entities, interfaces, and features that are absent.
- Note the intended product boundaries, trust boundaries, and deployment model.

### 2. Build a consistency map

Map:

- Entities, owners, and relationships.
- API operations and authorization boundaries.
- State machines and terminal states.
- Synchronous and asynchronous boundaries.
- Persistence, streaming, cancellation, retry, and recovery paths.
- Dependencies between specifications and their required implementation order.

Compare each claim against every related schema, endpoint, interface, and lifecycle rule.

### 3. Challenge the abstractions

Check whether:

- Dependency direction preserves domain boundaries.
- Interfaces contain enough typed behavior to be implemented.
- Provider- or transport-specific concepts leak into core logic.
- Named types without contracts hide unresolved design decisions.
- Required inputs, outputs, errors, ownership, and cancellation semantics are explicit.
- A referenced subsystem is defined before another subsystem depends on it.

### 4–6. Challenge the schema, runtime behavior, and API/security contracts

Work through [references/checklists.md](references/checklists.md): tenant-safe keys and constraints, deterministic ordering, transactions, secrets; concurrency, retries, restarts, multiple instances, cancellation, partial failure; authorization, identifier substitution, validation, pagination, update semantics, streaming, SSRF and secret exposure. Flag any behavior that depends on process-local state when the system must support multiple instances.

### 7. Challenge the Testability section

For a `feature`/`change` spec with state, a UI flow, or an integration ([write-specs template](../write-specs/references/testability.md)):

- Each new state, flow, and integration has an inspect command with named fields and a driver that reaches it without the UI or the model.
- Each failure and recovery path the requirements name has a fault or mock, and a Verification line pairs it with a tool.
- Each tool is reusable: a generic command with subcommands, flags, JSON output, and `--help`, registered in the toolkit with a smoke test. Ask: could a different tester reuse this tool for a new scenario without editing it? A one-off script, test procedure, or fixture-bound program is a finding.
- A missing section, or `Not applicable` on a spec that adds state, is a High finding.

### 8. Test implementability

For each feature, ask: could two engineers independently implement this and produce compatible behavior without making product decisions? If not, identify the exact missing decision.

## Severity

- **Critical:** permits data isolation failure, corruption, insecure behavior, or makes a core workflow impossible.
- **High:** produces incompatible implementations, broken lifecycle behavior, or major operational failure.
- **Medium:** leaves important validation, performance, or API behavior ambiguous.
- **Low:** wording, organization, or maintainability issue without immediate correctness impact.

Do not inflate severity. A missing detail is not automatically a defect if the specification deliberately leaves it to implementation.

MVP scope does not change severity. Risk acceptance is a separate decision made by the user after the finding is reported.

## Output Format

Lead with a direct readiness verdict. Then provide:

1. Findings ordered by severity.
2. For each finding: evidence, impact, and the decision or correction needed.
3. Separate sections for database, abstractions, API/security, runtime lifecycle, and structure when relevant.
4. A short list of strengths worth preserving.
5. A recommended specification order or next decisions when dependencies are incorrect.
6. A complete decision-question list, grouped by topic, when user input is needed.

Keep the report concise. Avoid repeating the specification, listing harmless omissions, or presenting personal preferences as defects.

Do not treat a reported risk as accepted. Only an explicit user decision can accept a risk, and accepted risks must be recorded through the `write-specs` workflow.
