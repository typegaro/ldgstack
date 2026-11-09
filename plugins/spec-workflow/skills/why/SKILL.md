---
name: why
description: Find out why code, a design, or a behavior is the way it is, from evidence - specs and their amendments, tracker records and decisions, git history and blame, PRs, issues, and any connected tools (issue tracker, chat, docs, error tracking) - with every claim cited. Use for "why was this built this way", "why did this change", before reshaping ownership or layering, or to seed bug hypotheses with regression history.
---

# Why

Answer from evidence, not from plausibility. Every claim gets a citation; a search that finds nothing is an answer ("no spec or commit explains it").

## Sources, in this order

1. **Specs.** `spec show <id> --effective`, `spec log <id>`, `spec graph`: the requirement, the decision specs, and amendments that shaped it. Accepted-risk `decision` specs often are the why.
2. **Tracker records.** Active and archived records (`implementation/`): requirements, bugs and their fixes, user decisions, blockers, `tracker decision list`.
3. **Git.** `git log -L` or `git log --follow -p` on the lines, `git blame -w -C` to the introducing commit, then that commit's message and diff. Look for reverts and re-lands.
4. **Forge.** The PR or local PR history, review threads, linked issues (`gh pr view`, `gh issue view`), when the project uses one.
5. **Connected tools.** If MCP servers for an issue tracker, chat, docs, or error tracking are available, search each for the symbol, file, or error text, in parallel subagents when there are several.

## Weigh the evidence

- Separate what a source states from what you infer; label inferences.
- Prefer the most specific and the most recent authoritative source (an accepted spec over a commit message, a decision over a chat guess).
- Note contradictions instead of resolving them silently.

## Report

The answer in two or three sentences, then the timeline of evidence with citations (spec IDs, commit SHAs, record and bug IDs, links), then what stays unknown.
