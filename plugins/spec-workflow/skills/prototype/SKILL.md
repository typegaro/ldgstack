---
name: prototype
description: Settle a design or empirical question with a throwaway sketch instead of asking the user or arguing - which layout, which interaction, which approach is faster, does the library behave as assumed - built in a scratch folder, variants behind one switcher, verified by observing them, with a recommendation. Use when a spec, plan, or review hits a question that running something could answer, for "prototype", "mock it up", "try both", or before writing a spec for new UX.
---

# Prototype

The prototype is an instrument for one decision. It is thrown away; the real build follows the normal spec run.

1. **Name the decision.** Which layout, density, flow, timing, API shape, or library behavior. No decision, no prototype.
2. **Classify the question.** If running something can answer it (behavior, timing, layout, output, performance), it is not the user's to answer: prototype it. Only a product or preference call no experiment settles goes to the user, as a `tracker decision add --waiting` call with your pick.
3. **Gather references** when the design space is open (prior art in the codebase, the project's design system, existing canvases). Skip when the direction is set.
4. **Build throwaway** in a scratch folder (`specs/.drafts/prototypes/<slug>/` or `/tmp/proto-<slug>/`), never in product source: plain HTML/CSS/JS or the smallest script that exercises the question; no framework, tests, or abstractions. For UI work in a project that uses design canvases, the canvas is the prototype.
5. **Compare alternatives side by side**: build two or three variants behind one switcher (buttons or a key), each labeled (`compare-designs`). Propose a variant the user didn't ask for when it is plausibly better.
6. **Observe.** Screenshot each variant at the sizes that matter (phone and desktop), drive the interaction, log the timing, print the output. The observation is the test.
7. **Recommend.** Variants, evidence, trade-offs, your pick, and the scratch path. Say plainly that it is throwaway. The chosen direction goes into the spec (link the evidence in its Context) or the plan.
