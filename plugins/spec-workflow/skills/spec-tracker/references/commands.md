# Tracker Commands

Every command takes the feature first, then any item ID.

```bash
tracker init specs/0000-project-bootstrap.md [--early]   # --early: dependencies in progress or startable; batches gate on **Requires:**
tracker status [0000-project-bootstrap]
tracker requirement list 0000-project-bootstrap
tracker requirement implemented 0000-project-bootstrap REQ-001 --evidence "..." [--location be/internal/database]
tracker requirement tested 0000-project-bootstrap REQ-001 --evidence "..."
tracker file add 0000-project-bootstrap be/internal/database/pool.go
tracker check add 0000-project-bootstrap --name go-tests --method "go test ./..." --result passed|failed|not_run|not_applicable --evidence "ok 14 packages"
tracker bug add 0000-project-bootstrap --title "..." --severity high --spec-ref "..." --environment "..." \
  --reproduction "..." --expected "..." --actual "..." --evidence "..."
tracker bug assign|fixed|verify|reopen|close 0000-project-bootstrap BUG-0000-project-bootstrap-001 ...
tracker blocker add 0000-project-bootstrap --summary "..." --report "<blocker report>"
tracker handoff 0000-project-bootstrap --to tester --completed "..." --remaining "..." [--checks-not-run "..."]
tracker gate 0000-project-bootstrap ready-test|acceptance
tracker spec-check 0000-project-bootstrap
tracker overlap [--depth N]          # changed files (or first N path parts) shared by active records
tracker overlap --plans              # pairs whose planned ownership globs / active lanes may select the same files
tracker tool-gap add 0000-project-bootstrap --capability ext.mock.oauth --requirement REQ-003 [--requirement ...] --why "..."
tracker tool-gap resolve GAP-0000-project-bootstrap-001 --tool fake-oauth --evidence "..."   # toolsmith; tool must provide it and pass verify
tracker tool-gap list [0000-project-bootstrap] [--open]
tracker toolkit list [--capability C] | summary | verify [name ...]
tracker toolkit add|update <name> --capability C --command "..." --location be/cmd/<tool> --smoke "..." --owner-spec 0022 --mode read-only|mutating [--guard "..."]
tracker toolkit remove <name> --reason "..."
tracker risk 0000-project-bootstrap high|normal --parent-confirmed      # high: fresh reviewer each round; normal: one review, then the fix diff
tracker bug follow-up 0000-project-bootstrap BUG-... --reason "..." --parent-confirmed [--user-decision "..."]   # low (medium with a decision) leaves the gate
tracker follow-ups                                                     # follow-up bugs in active and archived records
tracker bug add 0000-project-bootstrap ... --parent-confirmed --found-by final-review   # the parent files a finding (e.g. the final review)
tracker restore 0000-project-bootstrap --touches REQ-003 REQ-007 --parent-confirmed      # narrow defect: only these requirements reset
tracker assign 0000-project-bootstrap --role implementer --from-plan --batch 2 --parallel --parent-confirmed   # one more executor, disjoint lane
tracker assign 0000-project-bootstrap --release --assignment ASSIGN-... --parent-confirmed                  # end one parallel lane (parent)
tracker join 0000-project-bootstrap --assignment ASSIGN-... --completed "..."                            # an executor ends its batch lane; siblings keep theirs
tracker worktree create 0000-project-bootstrap [--repos be fe] [--base <branch>] --parent-confirmed   # <repo>/<branch> checkouts
tracker worktree status [0000-project-bootstrap]                       # changes, ahead/behind main, merged, test slot holder
tracker worktree merge 0000-project-bootstrap --parent-confirmed       # after the acceptance gate; all repos or none
tracker worktree remove 0000-project-bootstrap [--force --user-decision "..."] --parent-confirmed
tracker toolkit verify [name ...] [--feature 0000-project-bootstrap]   # worktree mode: smokes run in <repo>/main, or that spec's checkouts
tracker abandon 0000-project-bootstrap --reason "..." --user-decision "..." [--superseded-by 87] --parent-confirmed   # split/replaced spec; record kept in implementation/abandoned/
```

Worktree mode (`implementation/workspace.json`) and the test slot are described in the orchestrator procedures. A tester brief refuses while `test_slots` other specs are being tested (`--parent-confirmed --user-decision` overrides).

The toolkit manifest (`implementation/toolkit.json`) is project-wide and CLI-only; see `test-toolkit` for capabilities and tool rules. Gap IDs are `GAP-<feature>-NNN`; `resolve` and `defer` take the qualified ID alone, or `<feature> GAP-NNN`.

Bug and blocker IDs are fully qualified (`BUG-<feature>-001`, `BLOCKER-<feature>-001`); the short forms (`BUG-001`, and `BLOCKER-001` in older records) are accepted too. `gate <gate> <feature>` still works but is deprecated.

Parent only:

```bash
tracker requirement import 0000-project-bootstrap [--exclude-amended] [--parent-confirmed]
tracker requirement add 0000-project-bootstrap --spec-ref "0:R4" --verification "observable acceptance criterion" [--parent-confirmed]
tracker requirement implemented|tested 0000-project-bootstrap REQ-004 --evidence "..." --evidence-from <check> --parent-confirmed
tracker check add 0000-project-bootstrap --name lint ... --parent-confirmed
tracker check waive 0000-project-bootstrap <check-name> --reason "..." --user-decision "..." --parent-confirmed
tracker bug close 0000-project-bootstrap BUG-0000-project-bootstrap-001 --reason "..." --user-decision "..." --parent-confirmed
tracker blocker resolve 0000-project-bootstrap BLOCKER-0000-project-bootstrap-001 --resolution "..." --parent-confirmed
tracker tool-gap add 0000-project-bootstrap --capability be.fault --requirement REQ-042 --why "..." --parent-confirmed   # parent fallback, any role
tracker tool-gap defer GAP-0000-project-bootstrap-001 --reason "..." --user-decision "..." --parent-confirmed
tracker spec-sync 0000-project-bootstrap --reason "..." --parent-confirmed
tracker archive 0000-project-bootstrap --parent-confirmed
```

`requirement import` adds one requirement per `- **R<n>**` bullet (continuation lines and nested items included, suffixed IDs like `R16a` kept) with `--spec-ref <id>:R<n>` and the Markdown-stripped text as verification. It also adds each older requirement a bullet cites after `replaces`, `amends`, or `removes` (`3:R11`, `22:R7, R9`, `9:R7-R9`); `--exclude-amended` skips those (spec-sync keeps the choice), `--include-amended` is an accepted no-op. It is idempotent. `spec-sync` re-imports itself: a requirement whose text changed, an amended target whose citing requirement changed, and a new requirement lose their implemented/tested marks (old evidence kept in `evidence_history`); unchanged ones keep theirs; removed ones retire. It reports `changed`, `added`, `retired`, keeps the generation and the plan, and marks the plan `stale` (shown in `status` and briefs, where `brief --batch N` still works with a warning) until a new `plan add`. Records with only hand-added requirements fall back to the old full invalidation plus `requirement import`.

Lanes and briefs (parent):

```bash
tracker assign 0000-project-bootstrap --role implementer --paths 'be/internal/db/**' be/cmd/migrate --parent-confirmed
tracker assign 0000-project-bootstrap --role tester --read-only --parent-confirmed
tracker assign 0000-project-bootstrap --release --parent-confirmed
tracker assign 0000-project-bootstrap --role implementer --from-plan [--batch N] --parent-confirmed   # the latest plan's ownership globs; early records also check the batch's Requires
tracker assign 0001-ui --role fixer --paths fe/src/chat/** --carve 'fe/tests/support/**' --from ASSIGN-0000-project-bootstrap-003 --parent-confirmed   # narrow glob out of another spec's active lane
tracker assign 0000-project-bootstrap --role toolsmith --paths 'tools/fault/**' --alongside --parent-confirmed   # beside an active fixer, disjoint lane
tracker join 0000-project-bootstrap --completed "..."   # the side toolsmith's last command
tracker brief 0000-project-bootstrap --role implementer [--batch N | --batch REQ-001..REQ-008 [--final-batch]] [--parent-confirmed [--user-decision "..."]] [--fresh]
tracker brief 0000-project-bootstrap --role planner
tracker claim ASSIGN-0000-project-bootstrap-001     # an agent's first command (from its brief)
tracker init specs/0003-x.md --parent-confirmed --user-decision "..."   # only to start before depends_on/amends are accepted
```

`status` shows `pending` steps (e.g. `spec-sync` then `requirement import` after `spec edit`); gates fail until they run.


Plans and questions:

```bash
tracker handoff 0000-project-bootstrap --to planner --completed "requirements derived" --remaining "plan it"
tracker plan add 0000-project-bootstrap --from - <<'PLAN'     # planner (or parent); validates the template headings
## Ownership
- `be/internal/db/**`
## Findings
...
## Batch 1: pool and migrations
**Requirements:** REQ-001, REQ-002
...
## Stop conditions
...
## Out of scope
...
PLAN
tracker plan show 0000-project-bootstrap [--batch 1] [--version 2]
tracker handoff 0000-project-bootstrap --to parent --question "plan names be/x.go:12 but it does not exist; use be/y.go?"
tracker answer 0000-project-bootstrap --text "use be/y.go; same function" [--replan]
tracker handoff 0000-project-bootstrap --to implementer --completed "..." --remaining "..." --parent-confirmed --reason "one-line fix"   # no plan
```

`brief --batch N` (a plan batch) carries only that batch's text and the ownership, and marks the last batch final. `brief --role implementer` refuses without a plan for more than 3 requirements or more than one area, and without `--batch` for more than 10 requirements, more than 2 areas, or a multi-batch plan; `--parent-confirmed` overrides both. Retest and fixer briefs list failed or `not_run` checks by exact name to re-record. `brief --fresh` releases the role's active assignment and issues a new one with the same paths (plan ownership if none), for a fresh agent on the next batch. Without `--fresh`, `brief` does the same automatically when an agent already claimed the assignment (stderr warning). Each brief has a `First turn:` line: one parallel read of the spec, `requirement list`, and (implementer) the files the plan batch names.

Requirements imported from a spec's `## Testability` section are flagged `testability`. Their `requirement implemented` evidence (including the light path) must name a registered toolkit tool whose smoke passed since its last change, plus its smoke check and `--help`, e.g. `--evidence "tool compute-fault (compute-fault crash --lease ID); --help documents it; smoke: toolkit verify compute-fault passed"`. The record stores the tool and its verification time.
