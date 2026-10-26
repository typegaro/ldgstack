# Challenge Checklists

## 4. Challenge the database schema

Check:

- Tenant ownership is enforced by keys and constraints, not only application statements.
- Foreign keys enforce the complete relationship, including parent ownership.
- Cardinality, uniqueness, nullability, role, range, and state constraints match the prose.
- Delete and update behavior agrees with exposed API operations.
- Ordering remains deterministic when timestamps tie or writes are concurrent.
- Transactions preserve invariants across multi-record operations.
- Indexes support foreign keys and expected access paths.
- Mutable configuration cannot silently rewrite historical meaning.
- Secrets have a defined encrypted envelope, rotation path, and redaction boundary.
- Status fields, timestamps, errors, and outputs cannot contradict one another.

## 5. Challenge runtime behavior

Walk through normal execution, then test:

- Concurrent requests.
- Duplicate requests and retries.
- Process termination and restart.
- Multiple backend instances.
- Cancellation during each state.
- Partial provider, database, or network failure.
- Reconnection to streams.
- Resource deletion while work is running.
- Configuration changes while work is queued.

Flag any behavior that depends on process-local state when the system must support multiple instances.

## 6. Challenge API and security contracts

Check:

- Authentication and authorization for every operation.
- Cross-user and cross-resource identifier substitution.
- Request validation, response shape, status codes, and safe errors.
- Pagination, idempotency, and transaction boundaries where required by the described behavior.
- Update semantics for omitted, cleared, and secret fields.
- Streaming authentication, event IDs, replay, completion, and retention.
- User-controlled URLs, credentials, logs, and events for SSRF or secret exposure risks.
