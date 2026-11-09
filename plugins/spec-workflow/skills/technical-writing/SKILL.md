---
name: technical-writing
description: Standard for documentation, READMEs, RFCs, specs prose, PR descriptions, handoff notes, and commit messages - pick one document type (tutorial, how-to, reference, explanation), write for the reader's task, use plain controlled English, and follow the project's commit rules. Use when writing or editing any of these.
---

# Technical writing

## Pick the type

Each document is one of these; don't mix them:

- **Tutorial**: a learner follows steps to a first success. Every step works as written.
- **How-to**: a practitioner gets one task done. Numbered steps, prerequisites first, no theory.
- **Reference**: facts to look up (commands, flags, fields, config). Complete, consistent, no narrative.
- **Explanation**: why the design is the way it is, alternatives, trade-offs.

A README is usually a short explanation plus a how-to for the first run, with reference linked out.

## Sentences

- Write for the reader's task: what they want to do, then how.
- One idea per sentence, short sentences, active voice, present tense, second person for instructions ("Run `make test`").
- One word per concept: once you call it a "spec", don't switch to "specification document".
- Keep articles ("the", "a"); don't write telegraph style.
- Prefer a plain verb to an `-ing` noun: "to configure" over "the configuring of".
- Global English: no idioms, no culture-specific jokes, no ambiguous pronouns.
- Code, commands, paths, and identifiers in backticks; full commands that can be copied.
- Then run `unslop`.

## PR descriptions (local PRs and GitHub)

A one-minute briefing for someone with the diff. Sections, dropping the empty ones: **Why** (problem and approach, 1-3 sentences), **What changed** (1-3 bullets), **Scope** (what it leaves out), **Trade-offs** (only rejected alternatives a reviewer would ask about), **Blast radius** (who it touches and why that's safe), **Verification** (real commands or flows and their results). Evidence artifacts (logs, screenshots, swarm tables) are linked, not pasted.

## Commit messages

Follow the project's rules first (CLAUDE.md, AGENTS.md, CONTRIBUTING). When they say nothing: one short imperative subject line naming what changed, a body only when the why isn't obvious, no restating the subject. Never add attribution lines the project or user forbids.
