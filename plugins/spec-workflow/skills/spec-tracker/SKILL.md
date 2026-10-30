---
name: spec-tracker
description: Reference for the implementation-record tracker CLI (requirements, checks, bugs, blockers, tool gaps, toolkit manifest, handoffs, gates) and the shared blocker-report and severity conventions. Load whenever acting as parent, planner, implementer, reviewer, tester, fixer, or toolsmith on a specification, before touching anything under implementation/.
---

# Spec Tracker

Implementation records under `implementation/active/` and `implementation/archive/` are managed only by this CLI. Its JSON is authoritative, its Markdown is generated; a hook blocks direct edits to both. Records are coordination state; `specs/` remains the source of truth.

Invoke it as `python3 <this skill's base directory>/scripts/spec_tracker.py` (or the plugin's `bin/spec-tracker` wrapper); `tracker` below stands for that. Spell it out in every Bash call: shell state doesn't persist between calls, and zsh doesn't word-split a `$TRACKER` variable.

Run from inside the project. The root is the nearest directory containing `specs/` and one of `CLAUDE.md`, `AGENTS.md`, `.git`; override with `SPEC_WORKFLOW_ROOT`. Put `--json` before the command for machine-readable output. Every subcommand has `--help`.

## Roles and handoffs

Each mutation requires the record's current role:

| Role | May do | May hand off to |
|---|---|---|
| parent | `requirement add/import`, `bug assign/close`, `check waive`, `blocker resolve`, `tool-gap defer`, `assign`, `answer`, `plan add`, `spec-sync`, `archive`, `restore`; light path (below) | planner, implementer, reviewer, tester, fixer, toolsmith (open tool gaps) |
| planner | `plan add`, `blocker add` | parent (after `plan add`) |
| implementer | `requirement implemented`, `file add`, `check add`, `blocker add` | reviewer, tester (see below), parent |
| reviewer | `check add`, `bug add`, `tool-gap add`, `blocker add` | tester (no open bugs or tool gaps), parent |
| tester | `requirement tested`, `check add`, `bug add/verify/reopen`, `tool-gap add`, `blocker add` | parent |
| fixer | `file add`, `check add`, `bug fixed`, `blocker add` | reviewer, parent |
| toolsmith | `file add`, `check add`, `tool-gap resolve`, `blocker add` | tester (no open tool gaps), parent |

Normal flow: `init` (the record starts with the parent, status `new`) → parent derives requirements → planner → parent (`assign --from-plan`) → implementer (executor, per batch) → reviewer → tester → parent. Findings go back through parent → fixer → fresh review → tester; tool gaps through parent → toolsmith → tester. No role hands off to the tester while a tool gap is open.

- Any subagent role may `handoff --to parent --question "..."` (status `needs_answer`) instead of improvising. The parent runs `answer <feature> --text "..."` (back to the asker, same status as before) or `--replan` (to the planner, status `planning`). Answers appear in later briefs' `Decisions`.
- `init --early` (parent) starts a spec whose unaccepted dependencies are all in progress or startable, without a user decision: the record stores `early` and `blocked_on`, `status` shows `blocked_on_pending`, `assign --from-plan [--batch N]` and `brief --batch N` refuse a batch whose plan `**Requires:** <ids>|none` line names an unaccepted spec (no line = all of `blocked_on`), and `gate acceptance` and `archive` fail until all of `blocked_on` are accepted. `--parent-confirmed --user-decision` overrides a batch (stored in `dependency_overrides`).
- `handoff --to planner --parent-confirmed` also works while the executor has implemented nothing. `handoff --to parent` straight after `init` is a no-op kept for old flows.
- `handoff --to implementer` needs a stored plan when the spec has more than 3 requirements or more than one area (top-level dirs of the implementer lane, plan ownership, changed files), unless `--parent-confirmed --reason "..."`. `handoff --to planner|tester` creates a read-only assignment when none is active.
- `implementer → tester` skips review only when a reviewer check already passed, every requirement implemented since then was also added since then, and no bug is unresolved. The handoff records `review_skipped`.
- With `--parent-confirmed`, the parent may `requirement add/import` and `blocker resolve` while the record is in any role; the role at the time is logged.
- **Light path** (parent role, `--parent-confirmed`): `requirement implemented|tested --evidence-from <check>` marks a requirement from an existing passed check (`tested` needs a tester check run after the requirement was implemented), shown as parent-attested in the record and gate. `check add` re-records a mechanical check the parent ran, never a reviewer's or tester's check.

`requirement list` (any role) shows IDs, spec references, and verification, without implementation evidence.

Only the parent agent passes `--parent-confirmed`; subagents never do. `--user-decision` must quote or faithfully summarize what the user actually said. Never fill it in with the parent's own judgment.

## Commands

Every command takes the feature first, then any item ID; every subcommand has `--help`, and every error names the fix command. Full catalog with examples: [references/commands.md](references/commands.md).

```bash
tracker status [<feature>]                      # open_tool_gaps, open_questions, plan_version, pending bookkeeping
tracker requirement list <feature>
tracker requirement implemented <feature> REQ --evidence "..." [--location path]
tracker requirement tested <feature> REQ --evidence "..."
tracker check add <feature> --name n --method "..." --result passed|failed|not_run|not_applicable --evidence "..."   # same name supersedes
tracker bug add <feature> --title "..." --severity critical|high|medium|low --spec-ref "..." --environment "..." \
  --reproduction "..." --expected "..." --actual "..." --evidence "..."
tracker bug fixed <feature> BUG --fix "..." --regression "<test that fails without the fix>"
tracker bug verify <feature> BUG --retest "..."      # also: bug reopen BUG --evidence; parent: bug assign BUG --fixer f
tracker tool-gap add <feature> --capability c --requirement REQ [--requirement ...] --why "..." [--parent-confirmed]   # resolve|defer|list
tracker toolkit add <name> --capability c --command "..." --location path --smoke "..." --owner-spec NNNN --mode read-only|mutating [--guard "..."]
tracker toolkit update <name> [any add flag]       # also: list, summary, verify [name], remove <name> --reason
tracker blocker add <feature> --summary "..." --report "<blocker report>"
tracker plan add <feature> --from FILE|-           # planner (or parent); plan show <feature> [--batch N] [--version V]
tracker handoff <feature> --to <role> --completed "..." --remaining "..."   # or: --to parent --question "..."
tracker answer <feature> --text "..." [--replan]   # parent
tracker gate <feature> ready-test|acceptance
tracker overlap [--depth N | --plans]            # --plans: planned/assigned globs that may select the same files
tracker assign|brief|claim ...                  # lanes and generated delegation prompts (parent); brief --fresh renews the assignment
tracker assign <feature> --role r --carve <glob> --from <ASSIGNMENT> [--paths ...] --parent-confirmed   # take a narrow glob from another spec's lane
tracker spec-sync <feature> --reason "..." --parent-confirmed   # re-imports; invalidates only changed/new requirements; plan kept, marked stale
```

**Claims.** `claim <assignment>` (an agent's first command) binds the agent to its lane; the hook refuses a second agent's claim. Every `brief` targets a new agent: when the role's active assignment is already claimed, `brief` reissues it (same paths, new ID, the old one released as `brief: claimed by an earlier agent`) and warns on stderr. This covers a finished agent and one that died at the usage limit. To continue the earlier agent instead, resume it with SendMessage and no new brief. `--fresh` forces a new assignment even when it is unclaimed.

**Toolsmith alongside the fixer.** With open tool gaps while the record is with the fixer, `assign <feature> --role toolsmith --paths <disjoint globs> --alongside --parent-confirmed` keeps the fixer's lane and sets `side_role: toolsmith`. The side toolsmith may run toolsmith commands (`tool-gap resolve`, `toolkit add|verify`), and its brief's next command is `tracker join <feature> --completed "..."`, which releases its lane. Handoffs to the reviewer or tester wait for `join`. A plain `assign` for the fixer keeps the side lane; `assign --release` ends both.

**Carve-outs.** `assign --carve <glob> --from <ASSIGNMENT>` moves a narrow glob, which must lie inside the other spec's lane, into the new assignment. The giving assignment records `carved` and the receiving one records `carved_from`. The hook treats the glob as outside the giving lane, and the giving role's brief shows `except <glob> (carved out to ...)`. An `assign` overlap error lists each overlapping pair, the narrowest existing non-overlapping globs, and the carve command when it applies.

Bug, blocker, gap, and assignment IDs are fully qualified (`BUG-<feature>-001`); short forms (`BUG-001`) are accepted.

## Gates

`ready-test` (also enforced on handoff to reviewer or tester) fails when: the spec hash changed, an open blocker exists, no requirements are tracked or any is unimplemented, no current-generation check passed, or the latest current-generation result of any check is `failed` (except a tester's own check, which the tester re-runs on retest). Handoff to the tester also requires a current-generation reviewer pass and fails while a tool gap is open. Restore, spec synchronization, reimplementation, and fixer work advance the implementation generation so stale review/test evidence cannot satisfy gates.

A gate error for a failed or `not_run` check names the role that must re-record it (the reviewer or tester for their own checks, else the fixer) and the parent's exact handoff command; that role re-records it under the same name.

`acceptance` additionally requires every requirement tested, every bug `verified` or `closed_not_a_bug`, no open tool gap (resolved or deferred with a user decision), no check whose latest result is `not_run` or `failed` (including the tester's own), a passing check **recorded by the reviewer**, and a passing check **recorded by the tester**. Static code reading alone cannot satisfy the tester's part. A passing gate lists parent-attested requirements and `not_applicable` checks.

A `not_run` check doesn't block review or (re)test handoffs, but it blocks acceptance: run it, or the parent asks the user for a waiver. Always name it in your report. A missing toolchain or database is an environment defect to fix, never a waiver reason. `not_applicable` (with the reason as evidence) is for a check that doesn't apply, such as a missing inspection `check all`; it never blocks.

`tracker archive` and `spec archive` recheck their gates, so chaining them after a failed gate archives nothing; still chain with `&&`.

## Severity

Use the same scale everywhere (bugs, review findings):

- **critical**: data isolation failure, corruption, insecure behavior, or an impossible core workflow.
- **high**: incompatible implementations, broken lifecycle, or major operational failure.
- **medium**: important validation, performance, or API behavior is wrong or ambiguous.
- **low**: wording, organization, or maintainability without immediate correctness impact.

## Blocker report

Use this structure for every specification blocker. Record it with `blocker add --report`, and return it to the parent:

```markdown
## BLOCKER: Short title

- Specification: `<id>:R<n>` or `specs/NNNN-slug.md` section
- Requirement: concise quotation or faithful summary
- Evidence: code, contract, schema, or runtime fact exposing the problem
- Impact: what cannot be implemented or verified safely
- Conflict: other specification or behavior involved, if any
- Decisions needed: exact questions the parent must resolve
- Options: compatible choices and their consequences
- Recommendation: preferred choice, labeled as a recommendation
- Work status: completed, untouched, and blocked areas
```
