# initial/

Pristine starting state of `md2html` for **Episode 5**.

On every run, `../agent.py` deletes `../sandbox/` and copies this directory there. The agent operates on `../sandbox/`.

**For this episode:** `md2html` as specified, plus a feature spec for adding a **LaTeX renderer** as a second output format alongside HTML. The task naturally decomposes across modules (CLI flag, new renderer, possibly extension hooks, tests) — making it a legitimate candidate for planner/executor orchestration.

The exact LaTeX-renderer spec will be decided as part of Episode 5 prep. See [`../../../../spec/md2html.md`](../../../../spec/md2html.md) §8 for forward-looking notes.
