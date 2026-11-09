---
name: how
description: Explain how a subsystem or feature works at the level a senior engineer needs to change it safely - overview, key concepts, the flow with file:line pointers, where things live, and gotchas. Fans out read-only explorers for large subsystems. Use for "how does X work", before planning or reviewing a change in unfamiliar code, or as the grounding step of architect, why, and blast-radius.
---

# How

## 1. Size the question

- **Narrow** (one function, one module, one flow): explore and explain yourself, or with one read-only subagent.
- **Wide** (a subsystem across packages, services, or the be/fe boundary): split it into 2-4 angles (e.g. the request path, the data model, the background jobs, the UI) and run one read-only explorer per angle in parallel (`Explore` subagent, brief says "do not edit files"). Each returns file:line pointers, the data shapes, and open questions, not file dumps.

State your reading of an ambiguous question and proceed; the user can redirect.

## 2. Explain

Write one explanation from the findings, with these sections (drop empty ones):

- **Overview**: what it does and for whom, in three sentences.
- **Key concepts**: the types, tables, and terms a reader must know, with where each is defined.
- **How it works**: the main flow step by step, each step with `file:line`.
- **Where things live**: packages, routes, tables, config, tests, inspection commands.
- **Gotchas**: invariants, ordering, caching, concurrency, and places where the code and the specs disagree.

Cite only lines you read. Say "not found" rather than guess. Mechanics only; history and motive are the `why` skill's job.
