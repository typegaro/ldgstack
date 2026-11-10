# migrate-then-delete

*Apply when introducing a new internal API while old callers still exist. Migrate callers and delete the old API in the same wave instead of preserving compatibility layers.*

- Find every caller first (search, the compiler, `blast-radius` for callers grep misses: other languages, configs, wire formats).
- Move every caller to the new API in the same change, then delete the old one. A shim kept "for now" becomes a second API to maintain.
- Update tests to assert the new contract, and delete tests that only protect pre-refactor implementation details.

**When this applies:**
- No external users depend on backward compatibility.
- The project can absorb coordinated breaking changes.
- The new API is part of a simplification or refactor initiative.

With external users (a published API, stored data, another team's service), keep a compatibility path with a named owner and a removal date instead.
