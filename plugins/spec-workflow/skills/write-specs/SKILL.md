---
name: write-specs
description: Create or evolve specifications in specs/ while strictly preserving the user's requested scope. Specs are append-only like database migrations, so an implemented spec is changed by writing a new linked spec. Also covers the requirement format, adversarial review, defined-later and accepted-risk items, and starting a spec from one of them. Use before creating or changing any specification, or when the user describes a feature, convention, or decision to specify.
---

# Writing Specifications

Specs are the truth about what the system is: features, architecture, conventions, decisions. They are not tickets. A wrong implementation under a correct spec is a bug in the code and needs no spec.

Specs evolve like database migrations. Each spec is a numbered file `specs/NNNN-<slug>.md` with a tool-generated header, and its links point only to older specs. Load `spec-cli` for the commands.

## Scope rules

1. Include only requirements the user explicitly provides, approved project policy, or recorded decisions.
2. Do not add, infer, expand, or invent requirements, behavior, architecture, edge cases, or acceptance criteria.
3. If essential information is unclear or missing, ask instead of writing it.
4. Keep every point brief, clear, and actionable. Preserve the user's intent; improve wording without changing meaning.
5. Ask every question needed to resolve material product, security, data, lifecycle, or compatibility decisions. Group them, with no arbitrary limit. MVP scope never reduces review depth.

## Create or edit?

- **New topic**: `spec new --title ... --kind feature|convention|decision [--depends-on ...] [--references ...]`. Never create spec files by hand; a hook blocks it.
- **Spec not yet accepted** (draft or in progress): the parent writes the new body to `specs/.drafts/<name>.md` and runs `spec edit <id> --from specs/.drafts/<name>.md --reason "..." --parent-confirmed` (the hook denies direct edits). An in-progress spec, or an edit that resolves a conflict between specs (`--conflict`), also needs `--user-decision` with the user's words. Prefer small edits. With an active record, `status` then lists `spec-sync` and `requirement import` as pending; run both and send the record back to the implementer if requirements changed.
- **Subagent proposals**: a subagent writes a body-only draft to `specs/.drafts/<name>.md` and reports it. The parent reviews it with this workflow and applies it with `spec new ... --from` or `spec edit <id> --from`.
- **Spec already accepted** (implemented): never edit it; the hook blocks it. Write a new spec with `--amends <id>` (it changes part of the target, which otherwise stays in force), `--supersedes <id>` (it replaces the target entirely), or `--kind removal --amends <id>`. Only for a purely editorial fix that changes no meaning (a typo or a broken link) may the parent `spec unlock` with a recorded user decision, edit, and `spec relock`.

Kinds: `feature` (behavior), `change` (modifies accepted behavior), `removal`, `convention` (cross-cutting rules such as pagination, errors, or the inspection CLI), `decision` (accepted risks and architectural decisions; no implementation).

## Requirement format

Every rule that someone could check is a numbered bullet:

```markdown
- **R1** [security] A user can list only chats they own.
- **R2** [ux] The chat list shows the newest chat first.
- **R3** (replaces 6:R3) When exhausted, `next_cursor` is present and `null`.
- **R4** (removes 6:R4)
```

- One testable statement per ID, numbered sequentially through the file. IDs are unique within the spec.
- An optional tag gives the kind of constraint: `[security]`, `[data]`, `[ux]`, `[api]`, `[perf]`, `[ops]`.
- Cross-references use `<id>:R<n>`, e.g. `6:R3`.
- Before acceptance, renumbering is fine. After acceptance, IDs are permanent: a newer spec changes or removes one with `(replaces X:Rn)` or `(removes X:Rn)` at the start of its own requirement.
- Context, rationale, flows, examples, and diagrams are free text around the requirements.

## Defined later and accepted risks

Two more numbered bullets keep track of what a spec leaves for later. `spec later` and `spec risks` list the open ones across every spec (`--json`, `--all` adds resolved ones).

```markdown
## Defined later

- **L1** Streaming to the browser: how replies stream, and what happens when the tab closes.

## Accepted risks

- **A1** Single database: an outage stops every tenant. Revisit when the first paying tenant onboards.
```

- `L<n>` (defined later): a question the user chose to answer in a future spec. The text before the colon is the suggested title of that spec; after it, what is left open. Write one instead of free-text "defined later" or "TBD" prose. The spec must stand without the answer; if a requirement can't be implemented without it, it is a missing decision, so ask.
- `A<n>` (accepted risk): a risk the user explicitly accepted (see Accepted risks below). After the colon: the chosen behavior, its consequence, and the revisit trigger.
- Number each kind sequentially in the spec, like `R<n>`; after acceptance the IDs are permanent. Reference them as `<id>:L<n>` and `<id>:A<n>`.
- A spec that defines an `L` item, or addresses an `A` item, is a normal spec created the normal way. It says so in its body with a line `Resolves 1:L1.` (several: `Resolves 1:L1, 4:A2.`), and links the source spec in `--references` (or `--depends-on`/`--amends` when that is the real relation). The source spec is never edited: `spec later --all` shows the item as resolved by the new spec. `spec validate` rejects a `Resolves` that names a missing item or a newer spec.
- If the new spec answers only part of the item, it adds its own `L` item for the rest.

## Testability section

A `feature` or `change` spec that adds or changes persisted or runtime state, a UI flow, or an external integration ends with `## Testability`: `- **R<n>** [ops]` requirements for its own testing and inspection plan, built with the feature as part of the same spec:

- **Inspection**: the exact inspect commands and fields added or changed (read-only, bounded, deterministic; secrets and the dev-target guard per `dev-inspection`).
- **Drivers**: tools that exercise the feature without the UI or the model, such as a CLI that creates and drives the resource, with JSON output.
- **Fault and mocks**: fault injection and external mocks for the failure and recovery paths.
- **Environment**: the `env.isolate` and toolkit support needed, and each tool's toolkit registration with a smoke test. New tests and tools are parallel-safe: per-worker state and ports, and no dependence on order.
- **Verification**: which scenario is tested with which tool. A spec that changes frontend UI includes the project's mobile audit (an `fe.audit` tool) on the routes it touches, when the toolkit has one.

Each tool is reusable: a durable, generic command (subcommands, flags, JSON output, `--help`) that works for any future resource or scenario of the feature, is registered in the toolkit with a smoke test, and is maintained when the feature changes. One-off scripts, test procedures, and scenario-specific programs don't count. A spec with no state, flow, or integration writes `Not applicable: <reason>`. Decisions and pure docs are exempt. Template and example: [references/testability.md](references/testability.md). `spec validate` makes a missing section an error for specs created by 0.7.1 or later.

## Workflow

1. Run `spec list`, `spec later` and `spec risks`, and read the related specs. Run `spec show <id> --effective` for any spec you build on, and read the `decision` specs and accepted risks that affect the work. If the request matches an open `L` or `A` item, start from it: its text is the starting question list, and the new spec says `Resolves <id>:<item>`.
2. Extract only the explicitly requested points, and ask about any ambiguity that would require assumptions.
3. Decide: `spec edit` (not accepted yet) or `spec new` with the right kind and links.
4. Write the body: concise context plus numbered requirements, and the `## Testability` section when it applies.
5. Load and apply `adversarial-spec-review`, then ask all resulting material decision questions.
6. Apply the answers and repeat the review until each remaining risk is resolved or explicitly accepted by the user.
7. Verify that every statement comes from the user, approved policy, or a recorded decision. Remove anything inferred.
8. Run `spec validate`.
9. When the user asks what to define next, or a spec is finished, offer the open items from `spec later` and `spec risks` (with the draft specs from `spec list`) and let the user pick.

## Accepted risks

- Never infer risk acceptance from MVP scope, urgency, or silence. A risk is accepted only when the user explicitly accepts it, or explicitly chooses an option whose stated consequence includes it.
- Record each accepted risk as an `- **A<n>**` item in the spec it affects: the chosen behavior, consequence, and revisit trigger (add rationale and guardrails when they matter). The spec's requirements state the actual chosen behavior; the item never replaces them.
- To address a risk, write a new spec with `Resolves <id>:A<n>`. Risks that span several specs, or that need a long rationale, may still be a `decision` spec titled "Accept: <risk>"; existing ones stay valid, and a newer spec that supersedes one closes it.
- When new work reaches a risk's revisit trigger (`spec risks` lists them), raise it again instead of silently carrying the risk forward.
- Never record unaccepted review findings as accepted risks.
