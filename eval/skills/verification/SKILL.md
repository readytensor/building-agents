---
name: verification
description: Verify your change before finishing. Run the project's test suite and confirm it passes; do not claim completion on unverified work.
tools: []
---

Before you stop, verify your work against the project's own tests, not your memory.

1. Find how the project runs its tests (look for a tests/ directory, pytest, or a
   test command in the README or pyproject/setup files).
2. Run the full suite with the bash tool (for a Python project, usually
   `python -m pytest -q`).
3. If anything fails, read the failure, fix the cause, and run the suite again.
4. Only stop once the tests you are responsible for pass and you have not
   regressed the rest of the suite.

Evidence before assertions: base "it works" on test output you actually saw.
