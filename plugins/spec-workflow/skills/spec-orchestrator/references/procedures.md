# Orchestrator Procedures

## Light path (trivial tracker bookkeeping)

Instead of spawning an agent for pure bookkeeping, the parent may, with the record in the parent role:

- `requirement implemented|tested <feature> <REQ> --evidence "..." --evidence-from <check> --parent-confirmed`, when an existing passed check already covers the requirement (for `tested`: a tester check run after the requirement was implemented). The record and gate output show it as parent-attested.
- `check add --parent-confirmed` to re-record a mechanical check you ran yourself (format, lint, type check). You cannot re-record a reviewer's or tester's check.

Never use it for behavior no independent check has exercised, to mark a requirement whose check failed, or to replace a review or test round. When unsure, delegate.

## Spec edits (audited)

Nobody edits `specs/NNNN-*.md` directly; the hook denies it. Write the new body to `specs/.drafts/<name>.md` (subagents may propose drafts there too), then:

```bash
spec edit <id> --from specs/.drafts/<name>.md --reason "..." [--user-decision "..."] [--conflict "4:R7,22:R3"] --parent-confirmed
```

It refuses accepted specs (amend them with a new spec, or `unlock` with a user decision first), requires `--user-decision` for in-progress or unlocked specs and for any edit that resolves a conflict (`--conflict`), and logs who/why in `spec log <id>`. For an in-progress spec, the record's `status` then lists the pending steps: `tracker spec-sync <feature> --reason "..." --parent-confirmed`, which re-imports the requirements itself: only requirements whose text changed (or whose citing requirement changed) and new ones lose their marks, removed ones retire, and the stored plan is kept but marked `stale` (the parent may replan). Send the record back to the implementer if requirements changed. Records with only hand-added requirements still need `tracker requirement import <feature> --parent-confirmed` afterwards (`pending` shows it). `spec promote` is a deprecated alias.

## Dependency start guard

`tracker init` and `handoff --to implementer` refuse a spec whose `depends_on`/`amends` targets are not accepted. `init --early` is the exception when every unaccepted dependency is in progress or startable (see Parallel scheduling). Otherwise, only when the user decides to start early: add `--parent-confirmed --user-decision "<their words>"`; the override is stored in the record and reported by `workflow-retro --conformance`.

## Lanes (assignments)

Before each delegation: `tracker assign <feature> --role <role> --paths <glob> ... --parent-confirmed` (reviewer/tester: `--read-only`). Globs are project-relative; `**` crosses directories; a glob without wildcards owns its whole subtree. `assign` refuses paths overlapping another active lane. The brief's first command (`tracker claim <assignment>`) binds the agent; the path-guard hook then denies its writes outside its paths and inside other lanes. When exactly one active assignment has the agent's role, the hook binds automatically. An unknown assignment is allowed with a warning. `assign --release` ends a lane; `archive` releases all of a record's lanes.

## Worktree mode

Each code repository is a folder of branch checkouts: `<repo>/main` holds accepted code, `<repo>/<branch>` one spec's work. `specs/` and `implementation/` stay in the project root (shared state).

```text
project/  specs/  implementation/workspace.json
  be/main/   be/spec-0083-git-ssh-keys/
  fe/main/   fe/spec-0083-git-ssh-keys/
```

```json
{"repos": ["be", "fe"], "main": "main", "branch": "spec-{id}-{slug}",
 "copy": {"be": [".env"]}, "env": {"be": {".env": {"DATABASE_URL": "postgres://localhost/none"}}},
 "setup": {"be": ["direnv allow"], "fe": ["direnv allow", "direnv exec . npm ci"]},
 "slots": {"review": 2, "test": {"stack": 1, "browser": 2}}, "lease": "2h",
 "ci": {"fast": {"be": ["direnv exec . go build ./...", "direnv exec . go vet ./..."], "fe": ["direnv exec . npm run typecheck"]}},
 "hooks": {"duplicate_numbers": [{"glob": "be/db/migrations/*.sql", "pattern": "^(\\d+)"}],
           "pr_check": [], "pre_merge": [], "post_merge": ["make -C docker deploy"]}}
```

- **Adopt** (with the user, between specs, no agent running): commit or stash each repo, then `mv be be.tmp && mkdir be && mv be.tmp be/main` per repo, update paths that pointed at `be/` (scripts, compose files, project instructions), write `workspace.json`, run `spec preflight` (it runs `cd <repo>` commands in `<repo>/main`).
- **Copied env files never point at shared state.** A spec checkout that inherits the dev `DATABASE_URL` (or any shared database, queue, bucket, or production credential) lets an agent migrate or write the dev environment with unaccepted code. Override every such key with `env` (it rewrites the copied dotenv file), so tests reach only isolated stacks (`env.isolate`).
- **Per spec:** `tracker worktree create <feature> --parent-confirmed` before the first writer (`--repos` defaults to the plan's ownership; the base is an unmerged dependency's branch, else main). `copy` brings untracked files (e.g. `.env`) and `setup` runs per new checkout. Briefs point toolchain commands and the `Worktree:` line at the checkouts. Lane globs stay repo-relative.
- **Rounds:** each writer handoff commits a checkpoint on the branch; reviewers diff `main...HEAD`. `tracker worktree status` shows changes, commits ahead/behind main, and merged state.
- **Accept:** the merge queue (below); without it, gate acceptance, `worktree merge` (checks every repo with `git merge-tree` and merges all or nothing), `spec preflight`, then `archive` (needs the merge; removes checkouts and branches).
- **Conflicts:** the fixer merges main into the branch in its checkout (`git merge main`), resolves, reruns the focused tests, and opens the PR again; an agent's resolution needs a fresh focused review. Migration numbers collide often: `hooks.duplicate_numbers` flags a branch that reuses a number main or another open branch has; renumber in the branch.
- **Abandon:** `worktree remove <feature> --force --user-decision "..." --parent-confirmed`.

## Local PRs, CI, and queues (worktree mode)

- **CI tiers:** `ci.<tier>.<repo>` commands run in `<repo>/<branch>` (sibling `../<repo>` paths are rewritten as for the toolkit), stop at the first failure, and are recorded as check `ci-<tier>` with commands, exit codes, seconds, branch and main SHAs, and a log under `implementation/ci/<feature>/`. Only CI runs record them. With a `ci.fast` tier, the acceptance gate needs a passing `ci-fast` on the branch's current SHAs (`tracker ci run <feature> [--tier full] [--parent-confirmed]` reruns it, e.g. after a toolsmith commit).
- **Open PR:** `tracker pr open <feature> --completed "..." --remaining "..."` (implementer or fixer) commits the checkout, needs commits on the branch, refuses on a `git merge-tree` conflict with main or a blocking PR check, runs the fast tier, then hands off to the reviewer. With a `ci` section a writer's direct `handoff --to reviewer` is refused. A refusal keeps the record with the writer. CI runs outside the project lock, so other agents' tracker calls don't wait for it.
- **PR checks:** whenever main moves (`queue run merge`) and on `pr status`, every open PR is re-checked: merge-tree against main, `hooks.duplicate_numbers` (a new file whose number main, or another open branch, already uses under another name; branch-vs-branch is a warning: the one merged second renumbers), and `hooks.pr_check` commands (run from the root with repo paths pointed at the branch; `SPEC_FEATURE`, `SPEC_BRANCH` set). A blocked PR's queue item stays waiting; `pr return <feature> --parent-confirmed` sends it to the fixer with an assigned bug.
- **Queues** (`implementation/queues.json`, CLI-managed): review, test, and merge. Items are waiting, granted (a slot is reserved; brief or resume the agent), holding (an agent claimed the role's assignment after the item was queued), or running (a merge). Handoff out of the role drops the item. A lease (`lease`, default 2h) moves a dead holder to the back of its band. `queue add <queue> <feature> [--class C] [--priority N] --parent-confirmed` sets a class or priority; `queue add merge` needs the acceptance gate.
- **Merge queue:** `queue run merge --parent-confirmed` takes the granted item: merge-tree conflicts return it to the fixer (nothing touched, fresh focused review required); else it merges main into the branch, runs the fast tier and `hooks.pre_merge`, and on failure returns it to the fixer (the merge commit stays on the branch). Otherwise it fast-forwards `<repo>/main`, archives the record and the spec, removes the checkouts, re-checks the open PRs (`conflicting_prs`), runs `hooks.post_merge` from the root on main, and reports `queue_next`.

## Splitting or replacing an unaccepted spec

With the user's decision: write the successors (`spec new --supersedes <old>` for the one that takes over, `--depends-on`/`--references` for the rest), then `tracker abandon <old feature> --reason "..." --user-decision "..." --superseded-by <new> --parent-confirmed` (the record moves to `implementation/abandoned/`, lanes are released, a worktree is kept) and `spec defer <old> --reason "..." --parent-confirmed` so `ready`/`next` skip it; it becomes `superseded` once the successor is accepted. Successors get new records, requirements, and plans: REQ numbers change, so the planner replans and may reuse the old plan (`tracker plan show <old>` before abandoning, or the abandoned record) as input. Code already written is carried into the successor's branch and marked implemented only after its executor checks it; tell the reviewer which files it covers when that code is already on main (it won't appear in `main...HEAD`).

## Resuming

- An agent stopped early (rate limit, interruption): resume that same agent with SendMessage before spawning a new one.
- Active record exists: resume the role its status requires.
- Record archived but spec not: retry `spec archive`.
- Archived spec hash changed (`validate` fails): stop and report source-of-truth corruption.
- Reimplementing accepted work: `spec restore` (only for code defects against an unchanged spec; contract changes need a new spec), then `tracker restore` (`--touches <REQ...>` keeps the untouched requirements' evidence), add any missing requirements, `handoff --to implementer` (or file the defect as a bug for the fixer), then review and test again before archiving.
- A reviewer check left `not_run` and re-run by the reviewer later in the same generation doesn't need a new test round; a new review after the test does.

## Completion

When the queue is empty:

1. Run the full formatting, generation, static analysis, architecture, migration, unit, and integration checks for every repository.
2. Run `tracker toolkit verify`, and the inspection CLI's `overview` and `check all` across the whole application; every violation is a defect. If the CLI has no `check all`, report that gap to the user.
3. Run cross-spec regressions: ownership, authorization, lifecycle, concurrency, execution, streaming, cancellation, recovery, and convention consistency across all endpoints.
4. Delegate one whole-codebase `spec-workflow:spec-reviewer` pass against all specs.
5. Record each finding with the spec it escaped from and the finder class that should have caught it (reviewer, tester, or none), so the retro can attribute escapes. For each defect, restore the owning spec (`tracker restore <feature> --touches <REQ...>` for a narrow defect: only those requirements reset), file it with `tracker bug add ... --parent-confirmed --found-by final-review`, and route it through fixer, review, and independent retest, then re-archive.
6. Report archived specs, checks, environment limitations, and confirmation that spec contents are unchanged (`validate`).
7. Offer a `workflow-retro --conformance` run over this session.

An empty queue is not completion; the final cross-spec gate must pass.

## Releasing the plugin

Never patch `~/.claude/plugins/cache/**` (the hook denies it). Fix the plugin source, bump its version, then `claude plugin marketplace update <marketplace> && claude plugin update <plugin>@<marketplace>`.
