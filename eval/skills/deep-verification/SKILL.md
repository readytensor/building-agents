---
name: deep-verification
description: Go beyond running the test suite - lint the change, measure test coverage of the new code, and probe edge cases the suite does not cover. Load for changes where correctness matters more than speed.
tools: []
---

Running the project's existing tests is the baseline for every task - you do
that regardless of this skill. This skill is the deeper pass for changes that
warrant extra scrutiny.

1. Coverage: run the tests with coverage reporting (for Python, usually
   `python -m pytest --cov=<package> --cov-report=term-missing` if coverage is
   available). Confirm the lines you changed are actually executed by at least
   one test; untested changed lines are unverified changes.
2. Lint/style: run the project's linter if it has one configured (look for
   ruff/flake8/pylint config). Fix warnings your change introduced; leave
   pre-existing warnings alone.
3. Edge cases: list the boundary conditions of your change (empty input, wrong
   types, extremes) and check whether the suite covers them. Probe any that are
   not covered with a quick targeted test run, and consider whether the project
   would want a regression test added.
4. Blast radius: search for other callers of what you modified and confirm
   they still behave (a targeted test run per caller area beats assuming).

Evidence before assertions, at a higher bar: for a deep-verified change you
should be able to say what the coverage of your new lines is, that lint is
clean, and which edge cases you probed.
