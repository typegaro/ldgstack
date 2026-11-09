---
name: spec-orchestrator
description: Autonomously implement every numbered specification in specs/ in dependency order, delegating implement → code review → independent test → fix → retest to subagents and archiving each accepted spec. Use when the user asks to implement all specs, continue the spec run, or reimplement an archived spec.
---

# Spec Orchestrator

You are the parent, in the main session (only it can start subagents). The tracker runs the workflow; you launch agents, answer questions, and bring the user the calls only they can make. `tracker` means `python3 <spec-tracker skill base directory>/scripts/spec_tracker.py` (or the plugin's `bin/spec-tracker`); spell it out in every Bash call.

## Before the first run

Worktree mode (`implementation/workspace.json`) and `implementation/preflight.json` exist (procedures › Worktree mode). Run `spec preflight` and `tracker toolkit verify`; if either fails, stop and fix it with the user. If no `convention` spec defines the developer inspection CLI, create it with the user first (`dev-inspection`, `write-specs`).

## The loop

1. Run `tracker next`. It advances every spec as far as the tracker can (starts ready specs, imports requirements, creates worktrees, hands records on, assigns bugs, takes queue slots, queues merges) and returns `actions`:
   - `launch`: start the named `agent` with its `brief` pasted **verbatim** as the prompt (add extra context only below it). Launch every launch action at once, in the background.
   - `answer`: an agent asked a question. Answer from the spec, the plan, and the code: `tracker answer <feature> --text "..."` (`--replan` for a design question). A product call goes to the user.
   - `user`: a call only the user can make (a blocker, a decision spec, a waiting decision). Ask with AskUserQuestion, then record it (the action names the command). Keep everything else moving meanwhile.
   - `merge`: run `tracker merge` as a background command. A conflict or a failure returns the spec to a fixer by itself; `main_red` means main fails the same way: fix main first.
   - `wait`: nothing to do for that spec yet (a queue slot, required specs).
   - `parent`: bookkeeping the tracker can't do alone; run the listed commands.
2. When any agent finishes or a background merge exits, run `tracker next` again. Don't poll; wake on completions.
3. Stop when `next` returns no actions and nothing is working, then follow Completion in [references/procedures.md](references/procedures.md) (report open `spec later` and `spec risks` items).

`next` also replaces stuck agents (no progress past their role's usual time): stop the old one and launch the fresh brief; retry a second time with a smaller scope or another model, then replan.

## Rules that stay yours

- **Specs are the contract.** Never edit them to fit code. Changes go through `write-specs` and `spec edit` with the user's decision. `L` (defined later) and `A` (accepted risk) items are never implemented on your own.
- **Independence.** Never pass a writer's report to a reviewer or tester. Briefs are the only prompts.
- **User decisions.** Waiving a check, closing a bug as not a bug, resolving a blocker the spec doesn't answer, deferring a tool gap, starting a spec before its dependencies are accepted, and editing an in-progress spec need the user's words (`--user-decision`). While the user is away, log them with `tracker decision add --waiting --pick "..." --risk "..."` and continue with the rest.
- **Decide the rest yourself** and log it: `tracker decision add --feature F --decision "..." --why "..." --evidence "..."`. A question running something can answer goes to `prototype`, not to the user.
- **Catch the user up** with `catch-up` when they return.

## When `next` isn't enough

Unusual cases (an early start on unaccepted specs, carving files between specs, a manual waiver, restoring an archived spec, splitting a spec) use the underlying commands in [references/manual-flow.md](references/manual-flow.md) and the tracker's [full reference](../spec-tracker/references/full-reference.md). Model tiers: planner and reviewer on the deep tier, writers and tester on the efficient tier (agent frontmatter); give a fixer whose fix failed retest the deep tier.
