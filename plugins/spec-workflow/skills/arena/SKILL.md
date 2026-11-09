---
name: arena
description: Run N parallel attempts at the same artifact (a design sketch, an implementation, an explanation) from one identical prompt, score them against a rubric with a judge from a different model, pick a base, and graft the best parts of the others. Use for "/arena", competing designs, a second opinion on an approach, or one-way-door decisions (architect uses it).
---

# Arena

The prompt is the contract: every candidate gets the same one.

1. **Frame.** Name the artifact. Write a 3-6 item rubric of concrete, gradeable criteria for this task; only the judge and you see it.
2. **Runners.** At least two, on different models when available (opus and sonnet; or another provider in OpenCode). Use more for several design directions. Each writes to its own worktree or `/tmp/arena-<slug>/candidate-<n>/` (`separate-shared-state`).
3. **Fan out.** Spawn all runners in one message, in the background. Each produces the artifact plus a short rationale: the alternatives it considered and why it rejected them. A runner with no output is a dropout; continue with the rest.
4. **Judge.** After all runners finish, one read-only judge on a model different from yours scores each candidate by sanitized label (no model names) against the rubric and recommends a base.
5. **Pick.** Read every candidate end to end and score each criterion yourself. Agreement with the judge confirms; disagreement means a bias or an ambiguous rubric, so read both rationales before deciding. Prefer the base a maintainer can extend most safely; when tied, the smaller surface.
6. **Graft.** Take the one or two things worth porting from each loser and fold them in by hand so the result stays one design. Convergent candidates need no graft. Wildly divergent ones mean the frame was vague: reframe and rerun.
7. **Verify** the result like any other output (`prove-it-works`).

Output: the artifact, the base and why, the judge's verdict, each graft and its source, what was rejected, dropouts, and the verification result.
