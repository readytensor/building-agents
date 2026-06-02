# Episode 3 — Context

**Concept:** what changes when tasks get long. Two paired mechanisms — managed history (so the agent doesn't lose what was said) and explicit completion (so the agent doesn't quit before the work is done).

**This episode's additions on top of Ep 2:** rolling-summary **compaction** + **done tool** (`raise TaskComplete(message)`) replacing the naive stop from Ep 1.

**Code:**
- `agent.py` — Ep 2's agent + the additions above
- `initial/` — `md2html` ready for a multi-file refactor
- `sandbox/` — gitignored, recreated on every run

**Run:**

```bash
python agent.py
```

**Full context:**
- `../../README.md` — companion code repo overview
