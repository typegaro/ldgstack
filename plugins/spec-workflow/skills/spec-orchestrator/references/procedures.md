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
{"repos": ["be", "fe"], "main": "main", "branch": "spec-{id}-{slug}", "test_slots": 1,
 "copy": {"be": [".env"]}, "setup": {"be": ["direnv allow"], "fe": ["direnv allow", "direnv exec . npm ci"]}}
```

- **Adopt** (with the user, between specs, no agent running): commit or stash each repo, then `mv be be.tmp && mkdir be && mv be.tmp be/main` per repo, update paths that pointed at `be/` (scripts, compose files, project instructions), write `workspace.json`, run `spec preflight` (it runs `cd <repo>` commands in `<repo>/main`).
- **Per spec:** `tracker worktree create <feature> --parent-confirmed` before the first writer (`--repos` defaults to the plan's ownership; the base is an unmerged dependency's branch, else main). `copy` brings untracked files (e.g. `.env`) and `setup` runs per new checkout. Briefs point toolchain commands and the `Worktree:` line at the checkouts. Lane globs stay repo-relative.
- **Rounds:** each writer handoff commits a checkpoint on the branch; reviewers diff `main...HEAD`. `tracker worktree status` shows changes, commits ahead/behind main, merged state, and who holds the test slot.
- **Accept:** gate acceptance, `worktree merge` (checks every repo with `git merge-tree` and merges all or nothing), `spec preflight`, then `archive` (needs the merge; removes checkouts and branches). Dependent branches rebase onto main afterwards.
- **Conflicts:** add a bug ("merge conflict in <files>"), hand it to the fixer, who rebases the branch onto main in its checkout and reruns the focused tests; then review the fix and merge again. Migration numbers collide often: renumber in the branch, or use timestamped migrations.
- **Abandon:** `worktree remove <feature> --force --user-decision "..." --parent-confirmed`.

## Resuming

- An agent stopped early (rate limit, interruption): resume that same agent with SendMessage before spawning a new one.
- Active record exists: resume the role its status requires.
- Record archived but spec not: retry `spec archive`.
- Archived spec hash changed (`validate` fails): stop and report source-of-truth corruption.
- Reimplementing accepted work: `spec restore` (only for code defects against an unchanged spec; contract changes need a new spec), add any missing requirements, `handoff --to implementer`, then review and test again before archiving.

## Completion

When the queue is empty:

1. Run the full formatting, generation, static analysis, architecture, migration, unit, and integration checks for every repository.
2. Run `tracker toolkit verify`, and the inspection CLI's `overview` and `check all` across the whole application; every violation is a defect. If the CLI has no `check all`, report that gap to the user.
3. Run cross-spec regressions: ownership, authorization, lifecycle, concurrency, execution, streaming, cancellation, recovery, and convention consistency across all endpoints.
4. Delegate one whole-codebase `spec-workflow:spec-reviewer` pass against all specs.
5. Record each finding with the spec it escaped from and the finder class that should have caught it (reviewer, tester, or none), so the retro can attribute escapes. For each defect, restore the owning spec and route the defect through fixer and independent retest, then re-archive.
6. Report archived specs, checks, environment limitations, and confirmation that spec contents are unchanged (`validate`).
7. Offer a `workflow-retro --conformance` run over this session.

An empty queue is not completion; the final cross-spec gate must pass.

## Releasing the plugin

Never patch `~/.claude/plugins/cache/**` (the hook denies it). Fix the plugin source, bump its version, then `claude plugin marketplace update <marketplace> && claude plugin update <plugin>@<marketplace>`.
