# Episode 2 — Tools

**Concept:** how the agent actually does things — a small set of general primitives plus the idea of *skills* (named Python helpers composed from those primitives).

**This episode's additions on top of Ep 1:** `read`, `write`, `grep` tools (alongside `bash`); a tiny `@tool` / schema helper to remove JSON-schema boilerplate; skills as a lightweight reusable-pattern idea.

**Code:**
- `agent.py` — Ep 1's agent + the additions above
- `initial/` — `md2html` with one planted bug (TBD)
- `sandbox/` — gitignored, recreated on every run

**Run:**

```bash
python agent.py
```

**Full context:**
- `../../README.md` — companion code repo overview
- `../../../README.md` — planning workspace (series plan)
- `../../../spec/md2html.md` — toy codebase spec
