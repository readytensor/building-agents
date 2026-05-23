# initial/

Pristine starting state of `md2html` for **Episode 2**.

On every run, `../agent.py` deletes `../sandbox/` and copies this directory there. The agent operates on `../sandbox/`.

**For this episode:** `md2html` as specified, plus **one planted bug** (in the lexer, parser, or an extension) that causes a specific test to fail. The agent's task is to find and fix the bug; tests should pass after the fix.

The specific bug to plant will be decided as part of Episode 2 prep (a separate planning artifact). See [`../../../../spec/md2html.md`](../../../../spec/md2html.md) §8 for forward-looking notes.
