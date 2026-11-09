---
name: no-comments
description: Have the comments in a diff reviewed by an agent that did not write them, then delete or rewrite the ones that don't explain a non-obvious why. Spawns the spec-workflow comment-reviewer subagent (read-only). Use before review handoff, or when asked to strip, audit, or "no-comments" a diff.
---

# No comments

An author defends its own comments, so a fresh reader judges them.

1. Collect the comments the diff adds or changes (`git diff <base>...HEAD`, code files only).
2. Spawn the `spec-workflow:comment-reviewer` subagent with the diff command and the list. It is read-only and returns one verdict per comment: `delete`, `rewrite: <text>`, `encode: <check>`, or `keep: <reason>`.
3. Apply the verdicts:
   - `delete`: remove it.
   - `rewrite`: replace it with the shorter why.
   - `encode`: the comment claims a rule (an invariant, an ordering, a format). Prefer making the code enforce it (a type, an assertion, a test) over writing it down; do it when it is cheap, otherwise keep the comment and say why in the handoff.
   - `keep`: leave it.
4. When a comment cites an outside rule you cannot check (a dependency's behavior, a platform limit, a protocol), keep it and mark it for the reviewer in the handoff instead of deleting it.
5. Rerun the focused tests; comments are not behavior, but an `encode` change is.

What survives: license headers, doc comments on exported APIs, links that explain what code can't, and a non-obvious why (a workaround's reason, a security or ordering constraint).
