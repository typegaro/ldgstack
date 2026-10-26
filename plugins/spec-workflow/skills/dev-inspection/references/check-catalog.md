# Invariant Check Catalog

Categories to cover. Derive concrete checks from the project's specs. Every check is a read-only query or probe that returns a violation count and a bounded sample of IDs.

## `orphan.*`: references to things that don't exist

- Child rows whose parent is missing. Look especially at relationships without a foreign key: soft references, polymorphic `owner_type`/`owner_id`, IDs stored in JSON.
- Rows whose owner was soft-deleted or is being deleted while the child stays active.
- Join-table rows pointing at a deleted side.
- Objects in blob storage with no DB row, and DB rows pointing at missing objects.
- Queue messages or jobs referencing deleted entities.

## `ownership.*`: tenant boundaries

- A child's owner differs from its parent's owner (e.g. a chat's user ≠ its agent's user).
- Resources shared across tenants where the spec says they are private.
- Credentials attached to a resource owned by a different user.

## `state.*`: contradictions inside a row or aggregate

- The status disagrees with its timestamps: `completed` without `completed_at`, `pending` with `started_at` set, `finished_at < started_at`.
- A terminal state alongside a still-active lease, or an error field on a successful row.
- Counters and denormalized fields that disagree with the rows they summarize.
- More than one "current" row where exactly one may exist (active version, default item).
- Sequence and ordering gaps or duplicates (event sequence numbers, positions).

## `stuck.*`: work that should have moved

- Running with an expired lease, running past its deadline, cancellation requested but still running.
- Pending longer than a threshold. Defaults are configurable, e.g. 5 minutes.
- Retries exhausted but not marked failed. Attempts above the configured maximum.
- Pipeline stages whose oldest item is older than the stage's expected latency.

## `consistency.*`: across stores and processes

- DB vs cache, DB vs search index, DB vs object storage counts or versions.
- Migration state vs the application's embedded migrations.
- Configured items that the runtime doesn't know about, and the reverse (e.g. registered workers, MCP servers, providers).
- An outbox or inbox with unpublished or unprocessed rows older than a threshold.

## `retention.*`: lifecycle and cleanup

- Expired rows that should have been purged (sessions, OAuth states, temporary uploads).
- Rows in a deleting state longer than the deletion SLA.
- Data that the spec says is removed on account deletion but still exists.

## `config.*`: settings

- Required settings missing or invalid for enabled features.
- Settings that differ between processes that must agree (e.g. a shared encryption key ID).
