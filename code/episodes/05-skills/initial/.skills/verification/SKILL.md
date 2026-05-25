---
name: verification
description: Use before claiming work is complete. Provides discipline and tools to verify thoroughly against every acceptance criterion — tests, lints, scope — and to call done() correctly when (and only when) criteria pass.
tools: [lint, coverage]
---

# Verification

Before you call `done()`: prove the work is correct against EVERY
acceptance criterion in the task, not just the obvious one. Most tasks
have more than one criterion ("tests pass" is usually the easy one).

## The verification checklist

1. **Re-read the original task.** Enumerate every acceptance criterion
   it mentions, explicitly or implicitly. Use `think()` to write them
   down — this is the audit trail.
2. **Run the test suite:** `bash("pytest -q")`. ALL tests pass?
3. **Lint:** `lint()`. Clean?
4. **(If applicable) Coverage:** `coverage()`. New code covered by
   at least one test?
5. **Scope check:** if the task said "keep the diff minimal" or "don't
   refactor unrelated code," run `bash("git diff --stat")` (or similar)
   to verify the diff is bounded to what the task required.
6. **Tie evidence to criteria:** for each criterion, point to the
   evidence that satisfies it. Use `think()` to write this out as a
   short list. Skipping this step is how silent regressions ship.
7. **Only then:** call `done(summary)`.

## Evidence-before-assertion

Never claim "tests pass" without having seen the pytest output in this
session. Never claim "lint clean" without having run `lint()`. Never
claim "done" without having ticked every criterion. **Your word for it
is not evidence.**

## `done()` is the only clean exit

A free-text "I've finished the implementation" without calling `done()`
leaves the agent loop with no signal — the run ends via naive stop and
the trajectory looks unfinished in any post-hoc review. Eps 3 and 4
both ended this way in recorded runs. **This skill exists to prevent
that failure mode.**

If all criteria check out: call `done(summary)`. The summary should
list what was done, what was verified, and any caveats or known
limitations.

If even one criterion fails: do NOT call done. Debug, fix, re-verify
from step 1.

## Counter-patterns

- Calling done() because the FIRST test passed without running the
  full suite.
- Calling done() because "I think it's right" without running anything.
- Skipping a criterion because it "looks obvious" (every silent
  regression starts here).
- Declaring completion in free text instead of via the done() tool.
- Treating verification as ceremony — racing through the checklist
  without actually reading the output of each step.
