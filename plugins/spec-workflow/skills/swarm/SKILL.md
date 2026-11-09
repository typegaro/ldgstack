---
name: swarm
description: Fan out N independent workers across slices (one per package, feature, route, or test lane) or as racing attempts, then aggregate one PASS/ISSUES/BLOCKED report. Use for coverage checks ("check every package"), verification lanes, parallel investigations, or "/swarm". For bake-offs that pick and graft a base, use arena instead.
---

# Swarm

1. **Frame.** State the done predicate and the report the swarm returns. Choose the shape: partition into slices, race N identical briefs, or both. For a race, declare up front how you pick: first pass, rank all, or best-of.
2. **Isolate.** Each worker that writes gets its own worktree or output path. Workers that verify name the exact commit (or tracker patch) and the method (sample count, order) in their brief and their result.
3. **Fan out.** Spawn every worker in one message, in the background. Each brief stands alone: goal, scope, its slice or arm, how to verify, what to report. Results are `PASS`, `ISSUES` (every provable issue, with evidence), or `BLOCKED` (what blocked it).
4. **Aggregate.** Drop a result that doesn't record the commit and method its brief named; respawn that worker once, then record a gap. A gap is not a pass. Coverage needs a result for every slice.
5. **Report** once: a result table, one line per issue, gaps and dropouts, and the race rule if used. No raw worker dumps.

Respect the project's resource limits: a laptop with one test stack runs stack lanes one at a time (`tracker queue hold test --class stack --run ...`) and only cheap lanes in parallel.
