---
name: sharpen
description: Make a request deeper, not bigger, before doing it - restate the user's goal and problem in your own words, then name what a top professional would do that wasn't asked, the raw material they'd start from, their methods and tools, and an outside check that would show the result is right, and hand back the rewritten request without doing the task. Use for "/sharpen", "restate my goal", before writing a spec from a short request, or when a request is vague.
---

# Sharpen

Don't do the task. Hand back a better request.

1. **Restate** the user's goal and the problem behind it in your own words, plus the smallest change you'd expect to meet it. A misreading costs one message here instead of a wasted run.
2. **Deepen**, in four short answers:
   - What would a top professional in this field do here that the request doesn't ask for?
   - What is the rawest material they would start from (logs, real data, the running app, the source) instead of a digest?
   - Which specific methods and tools would they use?
   - What, other than you or the user, would show the result is right (a test, a metric, a user, a reference implementation)?
3. **Rewrite the request** to ask for exactly that. Leave choices that belong to the user open instead of deciding them.

In a spec run, `write-specs` uses steps 1-2 before drafting, and every brief opens by restating the goal (the tracker brief asks for it).
