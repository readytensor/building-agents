# Episode 2 — Tools

**Concept:** how the agent actually does things — a small set of general primitives the model can compose.

**This episode's additions on top of Ep 1:** `read`, `write`, `edit`, `grep` tools (alongside `bash`); a tiny `@tool` / schema helper to remove JSON-schema boilerplate.

**Code:**
- `agent.py` — Ep 1's agent + the additions above
- `initial/` — `md2html` with one planted bug (an escaped-backtick rendering failure)
- `sandbox/` — gitignored, recreated on every run

**Run:**

```bash
python agent.py
```

**Full context:**
- `../../README.md` — companion code repo overview
