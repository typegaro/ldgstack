---
name: blast-radius
description: Find what a change can break outside its diff and prove the one fact that makes it safe by running real code - not by writing a convincing argument. Looks past grep (library source, timing, wire formats, DB columns, other languages, flags, downstream consumers). Use for "what could this break", a small diff you don't trust, high-risk specs, or merge-resolution reviews.
---

# Blast radius

A list of callers is not the job; grep gives that in seconds. The job is the breakage grep won't show.

## Steps

1. **Read the change**: the diff, every symbol it adds, changes, or deletes, and what now behaves differently, including what the diff doesn't spell out.
2. **Find the one fact it's safe because of.** Most risky-looking changes are safe because of a single fact ("this only drops entries that are already expired"). Find it; spend your time there.
3. **Look where grep stops**: the library's source at the pinned version and local patches, execution timing (goroutines, transactions, React effects, teardown), JSON an API returns, DB columns and migrations, wire formats read by the other repo, feature flags, code a few hops downstream, inspection commands and toolkit drivers that read the same state.
4. **Rate each risk honestly**: how it breaks, `file:line`, likelihood, cost. Keep confirmed risks; list checked-and-cleared ones separately.
5. **Prove the fact.** Write a small script or test that calls the real code and fails loudly if the fact is false; run it; paste the output. How sure you are, from weakest to strongest: you said so, you cited the line, you walked the failure and it can't reach, you ran it, you reproduced it in the running app. Say where you stopped.
6. **For a wide change**, run the question through `arena` with two different models and merge the answers.

## Report

What it does (including the non-obvious part), the safety fact with its proof level and output (or "unproven"), the risks with evidence, what was cleared, and the cheapest check that would catch the real bug before merge, including the script you wrote. In a review, unproven risks are filed with `--unproven`.
