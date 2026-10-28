---
name: spec-cli
description: Git for specs. Use to create numbered specs, list them with derived status, link them (depends_on/amends/supersedes/references), inspect a spec's effective text and history (show --effective, log, graph), validate specs/, run preflight, archive or restore accepted specs, unlock/relock a frozen spec, or adopt a legacy specs/ directory.
---

# Spec CLI

Invoke it as `python3 <this skill's base directory>/scripts/spec.py` (or the plugin's `bin/spec` wrapper); `spec` below stands for that. Spell it out in every Bash call: shell state doesn't persist between calls, and zsh doesn't word-split a `$SPEC` variable. Add `--json` before the command for `{"ok":..,"result"|"error"}`.

```bash
spec new --title T --kind K [--slug S] [--depends-on 1,2] [--amends 6] [--supersedes 3] [--references 0,2] [--from specs/.drafts/F.md]
spec list [--kind K] [--status S] | status | ready | next | waves | next-number | validate [--strict-testability] | preflight
spec show <id> [--effective] | log <id> | graph [--mermaid]
spec archive <id> --parent-confirmed
spec restore <id> --reason R --parent-confirmed
spec unlock <id> --reason R --user-decision U --parent-confirmed
spec relock <id> --parent-confirmed
spec defer <id> --reason R --parent-confirmed   # undefer <id> --parent-confirmed
spec edit <id> --from specs/.drafts/F.md --reason "..." [--user-decision "..."] [--conflict REFS] --parent-confirmed
spec adopt --parent-confirmed [--dry-run] [--assign <stem>=<kind> ...] [--baseline <stem> ...]
```

`<id>` also accepts the file name. `ready` lists every draft or in-progress non-`decision` spec whose `depends_on` and `amends` targets are all accepted; `next` is the lowest of them. `list` shows `waiting_on` for the rest. A dependency cycle (only possible in an invalid `specs/`) is an error.

`waves` (scheduling, `--json` for machines) lists `startable` (= `ready`), `plannable` (draft specs whose unaccepted dependencies are all in progress or startable, with `blocked_on`; candidates for `tracker init --early`), `waves` (topological levels of every remaining non-decision spec), and `deferred` (shown separately, in no other list).

`defer <id> --reason R` parks a draft spec: a derived `deferred` status recorded in the manifest history (like `unlock`/`relock`; the spec file is untouched), so `ready`, `next` and `waves` skip it, `list` shows `[deferred]`, `tracker init` refuses it, and it stays a valid link target. `undefer` reverses it. Only drafts can be deferred.

`new`, `edit`, `archive`, `restore`, `unlock`, `relock`, `defer`, `undefer`, `promote`, and `adopt` are parent-only; the hook denies them to subagents.

## Files

Specs are append-only, like migrations: `specs/NNNN-<slug>.md`. Only `specs/README.md` may sit beside them. Always create specs with `new`; never create, rename, or hand-edit the frontmatter. `new` writes this frontmatter (exact key order) and a skeleton body:

```
---
id: 19
slug: chat-pagination-fix
title: Chat pagination fix
kind: feature
created: 2026-10-22
depends_on: []
amends: [6]
supersedes: []
references: [0, 2]
---
```

`kind`: `feature`, `change`, `removal`, `convention` (binds every later spec), `decision` (no implementation; archived without a record).

`archive` refuses a spec without at least one non-empty `- **R<n>**` bullet, decisions included.

## Drafts

`specs/.drafts/` holds body-only Markdown proposals (no frontmatter). Anyone, subagents included, may write there; the catalog ignores it. The parent applies a draft with `new ... --from <draft>` (new spec) or `edit <id> --from <draft> --reason "..."` (replace the body of a spec that is not accepted, or unlocked; `promote` is a deprecated alias). Both delete the draft. Nobody edits spec files directly (the hook denies it). `edit` logs reason and user decision in `log <id>`, and requires `--user-decision` for an in-progress or unlocked spec and with `--conflict`. Afterwards the record's `status` lists `spec-sync` and `requirement import` as pending.

## Relations

Links point only to lower ids and live only in the newer spec. Reverse links are computed.

- `depends_on`: the target must be accepted first; `ready` and `archive` enforce it.
- `amends`: changes part of the target; the rest of the target stays in force. `ready` also waits for the target to be accepted.
- `supersedes`: replaces the target entirely.
- `references`: context only.

`show <id> --effective` prints the spec followed by every spec that transitively amends or supersedes it, in id order. Read it before implementing or testing anything that touches the spec.

## Status

Derived, never stored: `draft` (no record, not archived), `deferred` (a draft parked with `defer`), `in_progress` (active tracker record), `accepted` (in `implementation/spec-archive.json`), `superseded` (an accepted spec supersedes it). `amended_by` lists the newer specs that amend it.

## Freeze

`new` stamps `workflow: <plugin version>` in the frontmatter. `validate` reports a `feature`/`change` spec without a `## Testability` section (see write-specs) as an error when it was stamped 0.7.1 or later, and as a warning otherwise.

Accepted specs are frozen: the hook blocks edits, and `validate` fails on a hash change. Change them with a new spec (`new --amends <id>` or `--supersedes <id>`). Only for a non-semantic fix with an explicit user decision may the parent `unlock`, `edit`, then `relock` (re-hashes the spec and the archived record).

## Requirements

- One requirement per bullet: `- **R<n>** [optional tag] text`. Tags: `[security]`, `[data]`, `[ux]`, `[api]`, `[perf]`, `[ops]`.
- Number sequentially within the spec. Cross-reference as `<id>:R<n>` (e.g. `6:R3`).
- Once a spec is accepted, its IDs are permanent. A newer spec starts its requirement with `(replaces 6:R3)` or `(removes 6:R4)`.

## Adopt (one-time legacy migration)

Run `adopt --dry-run` first. Legacy files named `N-slug.md` keep id N and get kind `feature`. Every other `.md` needs `--assign <stem>=<kind>`; those files get the next ids in `--assign` order (`--assign` on a numbered stem only overrides its kind). Adopt adds frontmatter, rewrites links to legacy file names, sets `references`, numbers top-level bullets outside code fences, renames files, and migrates tracker records and the manifest. `--baseline <stem>` marks an already-satisfied legacy spec accepted without an implementation record (it cannot be restored; amend it instead). It refuses to run when any spec already has frontmatter. Review the numbered bullets afterwards, then run `validate`.
