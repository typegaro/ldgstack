---
name: typescript-practices
description: Concrete TypeScript rules that turn type-discipline into syntax - strict mode, no any, unknown plus parsing at boundaries, discriminated unions with exhaustive switches, branded IDs, readonly data, schema-derived types, and typed errors. Use when writing, fixing, or reviewing .ts or .tsx files.
---

# TypeScript practices

Project rules (tsconfig, lint config, AGENTS.md) win over this list.

- **Strict mode stays on.** No `any`, no `@ts-ignore`, no `as` casts to silence an error. `@ts-expect-error` only with a reason and a test that proves the expectation.
- **External data is `unknown`** until a parser turns it into a domain type at the boundary: fetch responses, `JSON.parse`, `localStorage`, URL params, form data, postMessage, env vars. Use the project's schema library (zod, valibot, or hand-written guards) consistently.
- **Discriminated unions over optional-field bags.** Model states as `{ kind: "loading" } | { kind: "ready"; data: T } | { kind: "error"; error: E }`, not `{ loading?: boolean; data?: T; error?: E }`.
- **Exhaustive switches.** End a switch over a union with a `never` check so a new variant fails to compile.
- **Brand IDs that must not mix.** `type UserId = string & { readonly __brand: "UserId" }`, created only by the parser.
- **Derive, don't duplicate.** Types come from the API schema, generated route types, or a single `as const` table (`typeof table[number]`), not hand-copied interfaces.
- **Readonly by default** for props, config, and shared data (`readonly`, `ReadonlyArray`, `as const`).
- **`satisfies` over annotations** when you want checking without widening.
- **Errors are values at boundaries.** Return a result union, or throw a typed error class; never `catch (e) {}`; narrow `unknown` in catch blocks.
- **No non-null `!`** unless the invariant is local and obvious; prefer narrowing.
- **React:** derive state instead of syncing it in effects; effects only for external systems; stable keys from data, not indexes; components take the narrowest props.
- **Tests** drive the component or function through its public interface (`test-behavior`), with typed fixtures built by the same parsers production uses.
