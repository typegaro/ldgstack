---
name: tdd
description: Fix a bug test-first when there is a cheap, focused test path - write the smallest regression test, watch it fail for the right reason, fix, watch it pass - and fall back to the closest executable check when a test would be brittle or expensive. Use for bug fixes (fixer rounds), "/tdd", or "write the failing test first".
---

# Test-first bug fix

1. **Pin the bug.** State the intended behavior, the current behavior, and the smallest input that shows the difference (the bug's reproduction is your start).
2. **Pick the narrowest existing test layer** for that code path: unit, component, integration, or the project's E2E driver. Don't build new harness just for this.
3. **Write the failing test.** It encodes the intended behavior from the spec or bug, not the current implementation (`test-behavior`).
4. **Run it before fixing.** It must fail, and for the reason the bug describes. A pass, or a failure for another reason, means the test is wrong: fix the test first.
5. **Fix** with the smallest production change that satisfies it, at the root cause (`fix-root-causes`).
6. **Rerun** the new test and the focused suite around it.
7. **Commit in story order** when practical: the failing test, then the fix (`verifiable-units`).

## When a test is the wrong tool

Skip a new test when it would mostly test mocks, pin implementation details, depend on timing or global state, need heavy infrastructure for a small fix, or be deleted right after. Use the closest executable check instead (a script, the CLI, the toolkit driver, a dev-inspection query) and record it as the bug's regression evidence. No test beats a bad test.

## Report

`bug fixed --regression` names the test (or check), the failure it showed before the fix, and the pass after.
