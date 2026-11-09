---
name: verification-map
description: Create and maintain the project's feature map for verification - one file per user-facing feature saying how to reach it, how to drive it with the project's toolkit, and what observable end state proves it works - plus launch, doctor, evidence, and cleanup steps, all proven by one live run. Use when a project has no scripted way to prove app behavior, when testers keep rediscovering how to exercise features, for "/verification-map", or for the periodic drift check.
---

# Verification map

The test toolkit (`test-toolkit`) lists tools by capability. The verification map lists the app by feature, so a tester (or a parallel verify lane) knows how to prove any feature without rediscovering it. It lives at `implementation/verification/` (a project may name another folder in `implementation/toolkit.json` under `"verification"`), and the toolkit's tools do the driving.

## Create

1. **Interview the repo, not the user.** From the code and docs, answer: what users touch (web UI, CLI, API, worker); how the app starts locally for verification (the project's own command, ports, env, seed data, test account); how an agent drives it (existing Playwright/E2E drivers, CLI harness, HTTP, inspection CLI); what evidence proves behavior (screenshots, response bodies, rows via dev-inspection, logs, exit codes); whether two instances can run side by side. Ask the user only what the code can't answer.
2. **Write `README.md`** with these sections, each with exact commands from this repo (no placeholders):
   - **Launch**: start from an empty data dir to a usable state (migrations, seed, account), and how to tell it's ready (usable, not just "port open").
   - **Doctor**: one read-only check that the instance is worth driving (process up, right build, port owned by this run, login works). Run it first whenever anything looks odd.
   - **Drive**: the driver recipe with real selectors, routes, and commands; stable handles (ARIA labels, data attributes, route paths) over coordinates.
   - **Evidence**: what to capture and where; prove the real user path, the resulting state, and side effects (rows, files, messages), not just the final screen.
   - **Cleanup**: tear down only what this run started (never by process name); evidence survives cleanup.
   - **Index**: one line per feature file.
3. **Seed one file per feature** (start with the top 3-5 by user value): `## Sub-features`, `## How to reach it (user view)`, `## Driving it`, `## Proof` (the observable end state), `## Gotchas`. If seed data lacks a precondition, the journey fails and the reason goes in Gotchas; never weaken the journey to pass.
4. **Prove it once end to end**: launch, doctor, drive one feature, capture evidence, clean up, confirm the evidence still exists. A map never executed is a draft. Register any helper script as a toolkit tool with a smoke test.

## Maintain (periodic, or after a spec changes a feature)

Edit only the map and its helpers, never product code.

1. **Index hygiene**: README index matches the files; fix missing, extra, or dead entries.
2. **Source wave**: one read-only subagent per feature file, in parallel, explains the feature from the current code, flags drift with `file:line`, and returns one live recipe.
3. **Reconcile**: merge recipes into as few app states as practical; spot-check cited drift; add features recent specs introduced (with a source path).
4. **Live pass** (required even when the source looks clean): one instance, driven serially, every feature at least once. Doctor before the first drive and after any failure; reset or relaunch rather than drive a wedged instance; clean up residue after each failed drive.
5. **Triage**: wrong description is map drift (fix it); working behavior the driver can't reach is a harness gap (fix the helper, re-drive it); broken behavior is a product regression (report it, file a bug or a spec; never paper over it in the map).
6. **Outcome**: `clean` (full coverage, nothing to change), `changed` (one commit of proven corrections), or `blocked` (what stopped it). Record it with `tracker decision add --phase verification-map`.

## In a spec run

Testers read the map for the touched features first and extend it when a spec adds or changes a user-facing feature (same spec, inside the tester's or toolsmith's lane). Parallel verify lanes split by feature file.
