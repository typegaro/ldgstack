# Determinism Contract

Every rule exists so that two runs can be diffed and any difference means the system changed, not the tool.

**Inputs**
- **Time is an argument.** Every time-relative computation (`--since 1h`, pending age, stuck thresholds, expiry) is evaluated against one `as_of` instant. It is resolved once per invocation, from `--as-of <RFC3339>` or the current time, and echoed in the envelope. Queries receive it as a parameter. Never call `now()`, `CURRENT_TIMESTAMP`, or the clock inside queries or check logic.
- **One snapshot.** All reads of one invocation come from one consistent snapshot (e.g. a single `REPEATABLE READ` read-only transaction). The envelope reports the snapshot identity where the store exposes it (e.g. WAL LSN or transaction snapshot). Data from several stores is read in a fixed order, and each store's snapshot point is reported.
- **No environment leakage.** Output never depends on locale, time zone, terminal width, TTY detection, color support, hostname, or process ID. Force UTC and the C locale internally.

**Computation**
- **Total ordering everywhere.** Every list, sample, and nested collection has an explicit ordering ending in a unique key. Never rely on database default order, map or dictionary iteration order, or concurrency completion order. Sort sets before output.
- **No randomness, sampling, or estimates.** A check's "sample" is the first N rows in the defined order. Counts are exact, or reported as `unavailable` when they time out; never use planner estimates such as `reltuples`.
- **Deterministic cursors.** A cursor encodes the last row's sort key plus a hash of the command and filters. It never holds server-side state, random tokens, or timestamps.
- **Deterministic truncation.** The byte budget is measured on the canonical serialization, so the same data always truncates at the same record and field.
- **Parallelism doesn't change output.** If probes or queries run concurrently, results are assembled in a fixed order.

**Serialization**
- **Canonical JSON.** Fixed key order (sorted, or a declared schema order), no insignificant whitespace variation, UTF-8, no NaN or Infinity.
- **Normalized values.** Timestamps are UTC RFC 3339 with a fixed number of fractional digits. Durations and sizes are integers in declared units (ms, bytes). Decimals are rendered as strings with fixed scale, never as floats. Enums use the application's canonical names.
- **Volatility is quarantined.** Values that cannot be deterministic go in the envelope's `meta` (`generated_at`, the tool's own runtime, snapshot IDs) or in a clearly separated `observed` section (live probe latency, service up/down). They never go in `data`. `snapshot` and `check` exclude `observed` unless `--probes` is passed.

**Side effects**
- **Inspection must not perturb what it inspects.** No ORM hooks that touch `last_accessed`, no cache warm-ups, no auto-migrations, no connection-time writes, no lazy-initialized rows.

**Proof**
- A determinism test runs every command and check twice against the same fixture with the same `--as-of`, under different `TZ`, `LANG`, and terminal settings, and asserts byte-identical `data`.
- A golden-file test pins the canonical JSON of representative commands. Any intended change to the output updates the goldens and bumps the schema version if the change breaks compatibility.
