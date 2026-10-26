# Command Families

Build the families that apply to the project; names are illustrative.

| Family | Answers | Examples |
|---|---|---|
| `overview` | Is everything up and current? | store connectivity and versions, migration state (current/behind/ahead/dirty), entity counts, queue depths, recent failures, optional API health probe |
| Resource `list` / `get` | What exists, and how is it related? | `users`, `orders --user <id> --status failed --since 1h`, `order <id>` with its references |
| Process drill-down | Where is this unit of work, and why? | `job <id>` (attempts, lease, deadline), `job <id> steps`, `job <id> events`, each paginated |
| `pipeline` | Is the processing flowing? | per-stage counts, oldest pending age, last success, lag, throughput window, stuck items |
| `services` | Are dependencies alive and configured? | version and health of each service and broker, read-only probes only |
| `check` | Do invariants hold? | orphan detectors, contradictions, stuck work, cross-store consistency (see below) |
| `snapshot <area>` | Exact state of one feature area | one deterministic bundle of the above for a section, for before/after diffs |
| `config` | What is the effective configuration? | effective values (secrets included), missing or invalid settings per command |
| `sql` | Anything not yet covered | one `SELECT`/`WITH`/`EXPLAIN` (never `EXPLAIN ANALYZE`) in a read-only transaction, same bounds; no cursor |
