# guard-the-context

*Apply when context is filling up: large outputs, long files, repeated reads, fan-out planning. Route bulk to subagents; keep summaries in the main thread, not raw payloads.*

**Why:** Context overflow degrades reasoning quality, creates compression artifacts, and halts progress.

**Pattern:**
- **Delegate bulk reading.** Searches across many files, logs, and transcripts go to a subagent that returns the conclusion with file:line pointers, not the dump.
- **Size phases and cap scope.** Limit files per phase, set turn budgets, account for mechanism costs.
- **Read the part you need.** Use line ranges, `grep`, `head`, and bounded inspection commands instead of whole files and unbounded output.
- **Keep findings, drop payloads.** After reading, write down what you learned; don't reread the same file to recover it.

The reader's working memory is finite too: see [reader-load](reader-load.md).
