# Episode 4 — Planning & Reflection

**Concept:** why agents spiral, and how to fix it. The episode opens with a failure gallery (runaway loops, hallucinated progress, scope drift) and traces each failure to a specific architectural gap.

**This episode's additions on top of Ep 3:** a lightweight **plan step** before the loop (agent writes a TODO scratchpad) + a **reflect step** triggered on tool error or repeated identical tool calls.

**Code:**
- `agent.py` — Ep 3's agent + the additions above
- `initial/` — `md2html` with an ambiguous failing test (TBD)
- `sandbox/` — gitignored, recreated on every run

**Run:**

```bash
python agent.py
```

**Full context:**
- `../../README.md` — companion code repo overview
- `../../../README.md` — planning workspace (series plan)
- `../../../spec/md2html.md` — toy codebase spec
