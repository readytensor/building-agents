# Episode 5 — Orchestration

**Concept:** when one agent is the wrong shape — and what multi-agent actually buys you (and doesn't).

**This episode's additions on top of Ep 4:** a second agent instance with its own system prompt and tool subset; a `delegate(subtask)` tool on the parent that spawns a child agent; minimal message-passing between them.

**Code:**
- `agent.py` — Ep 4's agent + the additions above
- `initial/` — `md2html` plus a spec for a LaTeX renderer to be added
- `sandbox/` — gitignored, recreated on every run

**Run:**

```bash
python agent.py
```

**Full context:**
- `../../README.md` — companion code repo overview
- `../../../README.md` — planning workspace (series plan)
- `../../../spec/md2html.md` — toy codebase spec
