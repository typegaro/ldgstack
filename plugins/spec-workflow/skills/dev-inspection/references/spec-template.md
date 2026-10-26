# Developer Inspection CLI

<!-- Template: instantiate with `spec new --kind convention` through the write-specs workflow, numbering the bullets as requirements (- **R<n>**). Replace every <placeholder> with a user-confirmed value and delete options that do not apply. -->

Provide a local, development-only CLI that gives AI agents and developers deterministic, bounded, read-only snapshots of the application's real state while building and debugging. It is development tooling, never a production or remote administration interface.

## Implementation boundary

- Implement the CLI in <language> at `<path>` as a separate entry point of <repository>.
- Reuse the application's configuration, store clients, schema, domain types, and enums. Do not duplicate application contracts in the CLI.
- Connect directly to <datastores: e.g. PostgreSQL, Redis, object storage, broker> with development credentials, so inspection works when the API is unhealthy.
- Load only the configuration the selected command needs.
- Optionally probe <services/health URLs>. Store inspection never depends on those probes. When a probe fails, still return the available diagnostics and use the unhealthy exit status.
- Never expose the CLI over the network or install it as a service.

## Development-target guard

- Refuse to run unless `<ENV_MARKER>=development` is set and every target host is in <host allowlist, e.g. localhost, 127.0.0.1, compose service names>.
- Fail closed: an unknown, missing, or non-allowlisted target is a configuration error, with its own exit status.
- The guard has no override flag.

## Read-only boundary

- Run every datastore session read-only: a read-only transaction (and a read-only role where available) for SQL, `GET`/`HEAD` only for HTTP, peek-only for queues, list/stat/get for object storage.
- Provide no cancellation, retry, requeue, repair, migration, seed, delete, or other mutation command.

## Disclosure

- Output every stored value as is, including credentials, tokens, password hashes, secret envelopes, and decrypted secrets where the application can decrypt them. No redaction. This plaintext output is an accepted local-development risk: decision spec <id>.
- Default list and overview output excludes large content fields (<e.g. messages, payloads, prompts>). An explicit `--content` option includes them, subject to the byte bounds.
- Document that output contains secrets and private data, and must not be pasted outside the development environment.

## Incremental feature requirement

- Build the CLI shell, the dev-target guard, `overview`, `commands`, `config`, and `sql` with project bootstrap.
- Every feature that adds or changes persisted or runtime state adds or updates, in the same work: structured commands for that state, an invariant check for each invariant its spec states, and suspicious-state categories for its failure paths.
- A feature is not complete until those commands and checks have been run against real development data.
- Keep commands for every existing feature, so earlier features and cross-feature relationships stay verifiable.
- Promote any ad hoc query used twice into a structured command or check.

## Command surface

- `overview`: connectivity and version of each store, migration state, entity counts, queue and pipeline depths, active and expired leases, recent failure summary, optional service health.
- `commands`: machine-readable catalog of every command and check, with purpose, filters, and output shape.
- `config`: effective configuration, including secrets, plus missing or invalid settings for each command.
- `<resource>` list/get commands per feature, with ID, owner, status, and time-range filters where the fields exist.
- `<process> <id>` drill-downs with independently paginated sub-views (`steps`, `events`, `attempts`).
- `pipeline [<name>]`: per-stage counts, oldest pending age, last success, lag, and stuck items.
- `services`: version and health of each configured dependency.
- `check [all|<category>|<id>]`: run invariant checks (below). `check all` is required from the bootstrap spec on, even while the registry is empty (it then reports zero checks and exits 0); the spec workflow's agents run it before every handoff.
- `snapshot <area>`: one deterministic bundle of the commands relevant to a feature area.
- `sql`: one `SELECT`, `WITH`, or non-executing `EXPLAIN` statement. Reject `EXPLAIN ANALYZE`, multiple statements, and anything else. It runs read-only with the same timeout and byte bounds. No cursor: the caller adds `LIMIT` and filters.

Expose a structured command only once its feature exists.

## Invariant checks

- Keep checks in one declarative registry with a stable dotted ID (`<category>.<name>`), a severity (critical/high/medium/low), a description, and a read-only query or probe.
- Each check returns a violation count and a bounded sample of offending IDs.
- Categories: `orphan`, `ownership`, `state`, `stuck`, `consistency`, `retention`, `config`. Thresholds (e.g. pending age, default <5 minutes>) are configurable.
- Any violation makes the invocation exit with the unhealthy status.
- These are diagnostic categories, not new persisted statuses.

## Determinism

- The `data` part of every result is a pure function of (store state, `as_of`, arguments). Repeated runs give byte-identical `data` on any machine.
- Resolve `as_of` once per invocation, from `--as-of <RFC3339>` or the current time, echo it in the envelope, and pass it as a parameter to every time-relative computation. Queries and checks never read the clock (`now()`, `CURRENT_TIMESTAMP`).
- Read all data of one invocation in one consistent read-only snapshot per store (e.g. `REPEATABLE READ`). Read stores in a fixed order and report each snapshot identity (e.g. LSN) in the envelope.
- Every collection has an explicit total order ending in a unique key; the default for lists is newest first with ID as tie-breaker. Never rely on default database order, map iteration, or concurrency completion order.
- No randomness, sampling, or estimates. Samples are the first N in the defined order. Counts are exact, or `unavailable` on timeout.
- Cursors encode the last sort key plus a hash of the command and filters; no server state.
- Canonical JSON: fixed key order, UTF-8, UTC timestamps with fixed fractional digits, integer durations (ms) and sizes (bytes), decimals as fixed-scale strings, canonical enum names.
- Output never depends on locale, time zone, terminal, TTY, hostname, or process ID.
- Volatile values (generation time, tool runtime, snapshot IDs) live only in the envelope `meta`. Live probe results (latency, up/down) live only in a separate `observed` section, which `snapshot` and `check` exclude unless `--probes` is passed.
- Inspection causes no side effects in the inspected stores (no access-time updates, cache warm-ups, or auto-migrations).

## Bounds

- Lists default to <20> records, maximum <100>. Pagination uses opaque cursors bound to the command, ordering, and filters.
- Never emit more than <64 KiB> per invocation, measured on the canonical serialization. Stop at a record boundary and return a truncation flag and a cursor. When a single field exceeds the remaining budget, truncate it and report its original byte length.
- Every datastore statement has a <5-second> timeout.

## Output contract

- Text mode for humans; JSON mode is the versioned agent contract.
- Every JSON result contains schema version, command, `as_of`, `meta` (generation time, snapshot identities), `data`, optional `observed`, truncation flag, and a nullable cursor. JSON mode writes exactly one JSON document to stdout, and nothing else.
- Errors have a stable code and a concise message, plus a `--detail` option for internal causes. In JSON mode, errors are one JSON document on stdout, with stderr empty.
- Value formats follow the Determinism section.
- Distinct nonzero exit statuses for: invalid arguments, invalid configuration (including the dev-target guard), connection failure, query failure, and unhealthy result (failed probe or check violations). Success, including an empty result, exits 0.

## Tests

- Fixture-database tests for every command and check. Each check has a passing fixture and a violating one.
- Determinism test: every command and check runs twice against the same fixture with the same `--as-of`, under different `TZ`, `LANG`, and terminal settings, and its `data` must be byte-identical.
- Golden files pin the canonical JSON of representative commands.
- Tests prove that the dev-target guard refuses non-allowlisted targets and that no command can mutate state.

## Documentation

- Connection configuration and dev-target markers.
- Direct invocation (<e.g. `go run ./cmd/inspect`>) and a thin <Make/just> target that forwards arguments.
- Short examples: overview, `check all`, filtered list, drill-down, pagination, JSON mode, snapshot diff, `--content`, raw SQL.
