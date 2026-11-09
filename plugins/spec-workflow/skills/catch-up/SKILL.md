---
name: catch-up
description: Catch the user up after they stepped away - in plain words, what changed since their last message (specs merged, verdicts, bugs found and fixed, stuck agents replaced), with the screenshots and diagrams the work produced, then every call only they can make, each with the parent's pick, evidence, and risk so they can decide from the reply alone. Also restates a dense message plainly ("say it simply"). Read-only. Use for "/catch-up", "what happened", "where are we", morning review, or "explain that in plain words".
---

# Catch-up

Read-only: change nothing, start nothing, post nothing.

## Gather

- Your own work and subagent reports since the user's last message.
- `tracker status`, `tracker pr status`, `tracker queue status`, `tracker stuck`.
- `tracker decision list` (decisions made alone, and the calls waiting on the user).
- `tracker follow-ups` for deferred bugs worth knowing.
- Check each number against its source before showing it.

## Write

- **First sentence**: what waits on the user, or that nothing does.
- **What happened**, under about 100 words, pictures first: screenshots and videos the work produced, a Mermaid diagram when it explains a dependency chain or a before/after (at most six boxes, plain labels). One short line per thing the user asked for, said the way you would say it aloud, with its state: done, running, failed, or not checked.
- **Calls waiting on the user**: for each, the call, your pick, what it changes for users, the evidence, and the risk (including what can't be undone). Group items that share a call; riskiest first. Never cut items to stay short: the reply grows with the number of calls. Give the command that records the answer (`tracker decision resolve D-NNN --answer "..."`).

Plain words: say "the tests pass", not "CI is green"; leave out hashes, paths, and counts unless the user needs them to act; call each spec by its number and title.

## Say it simply

When the user asks for a plain restatement of a message, rewrite it as one person talking to another: shorter, no jargon, same facts, same open decisions.
