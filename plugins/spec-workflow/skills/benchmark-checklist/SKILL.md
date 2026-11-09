---
name: benchmark-checklist
description: Vet a measured number (a speedup, a regression, a latency, a throughput, an eval or retro result) before reporting or acting on it - what limits it, tuned and equal sides, physical limits, errors and skipped work, repeat runs with median and range, end-to-end relevance, and work inside the timed region. Returns faster, slower, no measurable difference, or inconclusive. Use for perf specs, benchmark results, workflow-retro numbers, or "/benchmark-checklist".
---

# Benchmark checklist

Before the number goes in a handoff, check, PR, or retro, answer each question with evidence from a run, not from reading code.

1. **What limits it, and why isn't it twice as good?** Name the bottleneck (a core, a lock, disk, network, the database, the load generator itself) from a profile or system counters taken during the run, and map it to source.
2. **Did both sides run as production runs?** Same build mode, flags, data size, warm or cold cache, connection pools, and concurrency. An untuned side makes any comparison meaningless.
3. **Does it break a physical limit?** More throughput than the disk, network, or core count allows means it measured something else.
4. **Did anything error or return wrong output?** Count errors and verify a sample of results; fast failures look like speedups.
5. **Does it reproduce?** Alternate the two sides (A B A B), several runs each, report the median and the range. If the spread is larger than the effect, the result is no measurable difference.
6. **Does it matter end to end?** Measure the path a user waits on. A 50% win on a step that is 1% of the request is a 0.5% win.
7. **Did the work happen inside the timed region?** Lazy evaluation, async work after the timer stops, caches primed outside the timer, and dead-code elimination all fake wins.

Write down, before running, which result would change the decision and what noise you expect.

## Verdict

`faster`, `slower`, `no measurable difference`, or `inconclusive`, with run count, median, range, and the named limiter. Say inconclusive when you can't name the limiter or a side ran untuned. Record perf checks with these facts in the evidence.
