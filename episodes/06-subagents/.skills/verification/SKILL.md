---
name: verification
description: Use before claiming work is complete. Provides discipline and tools to verify thoroughly against every acceptance criterion — tests, lints, scope — and to stop only when (and only when) every criterion passes.
tools: [lint, coverage]
---

# Verification

Before you treat the task as complete: prove the work is correct against
EVERY acceptance criterion in the task, not just the obvious one. Most
tasks have more than one criterion ("tests pass" is usually the easy one).

## The verification checklist

1. **Re-read the original task.** Enumerate every acceptance criterion
   it mentions, explicitly or implicitly. Write them down — this is the
   audit trail.
2. **Run the test suite:** `bash("pytest -q")`. ALL tests pass?
3. **Lint:** `lint()`. Clean?
4. **(If applicable) Coverage:** `coverage()`. New code covered by
   at least one test?
5. **Scope check:** if the task said "keep the diff minimal" or "don't
   refactor unrelated code," run `bash("git diff --stat")` (or similar)
   to verify the diff is bounded to what the task required.
6. **Tie evidence to criteria:** for each criterion, point to the
   evidence that satisfies it. Write this out as a short list.
   Skipping this step is how silent regressions ship.
7. **Only then:** stop calling tools and write a clear final summary.

## Evidence-before-assertion

Never claim "tests pass" without having seen the pytest output in this
session. Never claim "lint clean" without having run `lint()`. Never
claim "done" without having ticked every criterion. **Your word for it
is not evidence.**

## Stopping IS the completion signal — so stop deliberately

The run ends the moment you produce a turn with no tool calls. That
final, tool-free summary is the only completion signal there is — there
is no separate "done" button to press, and no second pass after it. So
treat the decision to stop as the decision to ship: do not stop until
every criterion above is verified. Stopping early with unverified work
is exactly the failure this skill exists to prevent.

When all criteria check out, stop and write a summary that lists what
was done, what was verified (with the evidence), and any caveats or
known limitations.

If even one criterion fails: do NOT stop. Debug, fix, and re-verify
from step 1.

## Counter-patterns

- Stopping because the FIRST test passed without running the full suite.
- Stopping because "I think it's right" without running anything.
- Skipping a criterion because it "looks obvious" (every silent
  regression starts here).
- Declaring completion without having actually run the checks.
- Treating verification as ceremony — racing through the checklist
  without actually reading the output of each step.
