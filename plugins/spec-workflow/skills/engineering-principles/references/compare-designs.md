# compare-designs

*Apply when facing a novel UI interaction or architectural decision with no precedent in the codebase. Build two or three competing sketches and compare them side by side before committing.*

- Make the sketches structurally different (different data shape, ownership, or interaction), not variations of one idea.
- Build each just far enough to answer the question: types and signatures for code (`architect`), a clickable variant for UI (`prototype`).
- Compare against named criteria, by observing the sketches run, not by arguing about them. `arena` runs the attempts in parallel and judges them.
- Pick one, graft the best parts of the others, and delete the losers.

It also applies to product design decisions where the experience depends on feel, not logic. Skip it when the codebase already has a precedent: follow the precedent.
