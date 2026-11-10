# smallest-change

*Apply when refactoring, judging how much a change adds, or tempted to add abstractions, layers, flags, or signal threading. Bias toward deletion and the least new surface that solves the problem.*

- **Consolidate decisions.** Do not repeat the same choice in several places. Put it behind one source of truth and pass the result as a simple value.
- **Add the least new surface.** No layer, flag, option, or abstraction the requirement does not need. Prefer deleting code to adding it.
- **Not a line count.** The measure is new concepts a reader must learn, not lines. A longer, explicit change beats a short clever one, and a diff is never judged by its size alone.
- **Remove the condition instead of compensating for it.** A mechanism that cleans up after a cause leaves the cause in place and adds work on every run.

Build the smallest script, type, or module that does the job, never a framework for jobs that don't exist yet.
