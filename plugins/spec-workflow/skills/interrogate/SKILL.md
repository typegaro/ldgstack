---
name: interrogate
description: Adversarial review where only findings proven by a run survive - several independent adversaries (different models when available) try to break a diff or design with failing tests, repro scripts, or command output; the coordinator reruns each and drops the rest. Use for contested or high-risk changes, "/interrogate this", a skeptical branch review, or a second opinion before merge.
---

# Interrogate

Adversaries try to break the change. Report findings; don't fix them.

## Frame

- **Scope**: what the user names, else the spec branch diff against its merge base with main (`git diff main...HEAD` in the checkout), plus uncommitted changes.
- **Intent**: restate it in your own words from the spec, the record's requirements, and the handoff. Ask only if it is truly unclear.

## Fan out

Spawn 2-4 adversaries in parallel, each in its own worktree or scratch copy (never the shared checkout), on different models when the harness allows (e.g. opus and sonnet in Claude Code; another provider in OpenCode). Each gets the scope, the intent, and this brief:

> Break this change. Prove each finding with a run against the real code: a failing test, a repro script, or command output showing the wrong behavior. For a design, probe the current code or a small prototype. Report each finding with a title, the exact command, the output it printed, and the output the intent requires. Leave out anything you did not run: style, naming, structure, hypothetical future risks. No findings is a valid result.

## Verify

Rerun every finding's command yourself. Keep it only when the output shows the failure and the failure breaks the intent. Merge findings with one root cause. A finding the base (main) already has does not count against this change unless the change copies it or newly reaches it.

## Output

- **Intent**: the restatement.
- **Findings**: each with command, output, how it breaks the intent, and which adversaries found it. Inside a spec run, the reviewer files each as `bug add --ran`. Say "no verified findings" when none survive.
- **Dropped**: per adversary, how many findings were dropped and why.
