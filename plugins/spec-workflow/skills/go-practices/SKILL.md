---
name: go-practices
description: Concrete Go rules that turn the engineering principles into code - context first, explicit wrapped errors, small consumer-side interfaces, domain types parsed at boundaries, no package-level mutable state, table-driven behavior tests, and safe concurrency. Use when writing, fixing, or reviewing .go files.
---

# Go practices

Project rules (AGENTS.md, convention specs, linters) win over this list.

- **`context.Context` is the first parameter** of anything that does I/O, waits, or calls out; pass it through, never store it in a struct, never use `context.Background()` below `main` or a test.
- **Errors are explicit.** Return them, wrap with `fmt.Errorf("doing x: %w", err)`, compare with `errors.Is`/`errors.As`, and define sentinel or typed errors for cases callers branch on. Never `_ =` an error that matters; never log-and-continue past a failure the caller should see.
- **Interfaces are small and live with their consumer.** Accept interfaces, return concrete types. No interface with one implementation and no second planned.
- **Parse at the boundary.** HTTP handlers, CLI flags, config, queue messages, and DB rows become validated domain types once; domain code trusts them. Distinct ID types (`type AgentID string`) where mixing would be a bug.
- **Keep domain logic out of adapters.** HTTP, SQL, and provider SDK code stays in thin adapter packages; the domain package imports none of them.
- **No package-level mutable state** (globals, `init()` side effects, singletons). State lives in structs created in `main` and passed down; this keeps tests parallel and instances independent.
- **Concurrency.** Every goroutine has an owner that waits for it (`errgroup`, `WaitGroup`) and a way to stop (`ctx`). Prefer giving each worker its own data to sharing a mutex (`separate-shared-state`). Close channels only from the sender. Run tests with `-race` where the project allows.
- **Idempotent operations.** Migrations, workers, and reconcilers converge when rerun; use upserts, unique keys, and state checks instead of "run once" assumptions.
- **SQL.** Parameterized queries only; every query that reads user-owned data filters by the owner; transactions for multi-statement invariants; handle `sql.ErrNoRows` explicitly.
- **Tests are table-driven** over behavior through the package's exported API, with `t.Parallel()` when isolated, `t.Helper()` in helpers, and real dependencies (a test database, an in-process server) over mocks where the project provides them.
- **Formatting and vetting** (`gofmt`, `go vet`, the project linter) are not optional and never suppressed without a reason on the line.
