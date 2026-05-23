# initial/

Pristine starting state of `md2html` for **Episode 4**.

On every run, `../agent.py` deletes `../sandbox/` and copies this directory there. The agent operates on `../sandbox/`.

**For this episode:** `md2html` as specified, plus **a failing test whose root cause is genuinely ambiguous across modules** (e.g., "tables inside nested lists render wrong" — the bug could legitimately live in the lexer, parser, or renderer). The ambiguity is the point: the naive agent dives into one module and spirals; the planning + reflection mechanisms earn their keep.

The specific failure will be decided as part of Episode 4 prep. See [`../../../../spec/md2html.md`](../../../../spec/md2html.md) §8 for forward-looking notes.
