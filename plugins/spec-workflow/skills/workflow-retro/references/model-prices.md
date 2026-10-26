# Relative model prices

`retro.py` reports `cost units` = weighted tokens × the model family's relative price. Weighted tokens already apply the
per-token-type ratios (input 1, cache write 1.25, cache read 0.1, output 5); the family price scales the whole run.

| Family | Default price (Opus = 1.0) | Typical roles since 0.7.0 |
|---|---:|---|
| opus | 1.0 | parent, planner, reviewer, escalated fixer, high-risk extra tester |
| sonnet | 0.6 | implementer (executor), fixer, tester, toolsmith |
| haiku | 0.2 | none by default |

Defaults are list-price ratios at the time of writing; check current pricing and override per run:

```bash
retro.py ... --model-weight opus=1.0 --model-weight sonnet=0.6 --model-weight haiku=0.2
```

A model id maps to the first family name it contains (`claude-sonnet-...` → sonnet); unknown ids are priced 1.0.
For other providers, pass family-specific weights explicitly, for example `--model-weight gpt-5.6-terra=1.0 --model-weight gpt-5.6-sol=0.6`; choose weights from actual provider pricing rather than assuming the Claude defaults are equivalent.
Runs tagged `[plugin-dev]` in the Agent description or prompt are reported as `plugin_dev` and excluded from workflow
totals, by-role, by-model, and findings.
