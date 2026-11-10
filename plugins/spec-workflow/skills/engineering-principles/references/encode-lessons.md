# encode-lessons

*Apply when you catch yourself writing the same instruction a second time, or notice a recurring correction. Encode the rule as a lint, metadata flag, runtime check, or script instead of more text.*

Prefer the highest level that works: change the architecture so the mistake can't be made, then a type, then a lint or CI or tracker/hook gate, then a test. Prose is the last resort. Prove the new check fails on a real past instance of the mistake before relying on it. The `correct` skill runs this across a repo.

If the lesson needs judgment and cannot be encoded, make the instruction more prominent and add an example of the failure mode.

**Corollary:** If the fix is structural, only use the structural fix. The instruction is the symptom.
