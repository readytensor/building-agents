# Episode 4 — Planning & Reasoning

**Concept:** add two reasoning-strategy tools to the Ep 3 agent — a structured plan tool (`write_plan`) and an in-the-moment reasoning tool (`think`) — and see what they actually buy you on a multi-step feature-add task.

**This episode's additions on top of Ep 3:**
- `write_plan(steps)` — Claude Code TodoWrite-style structured plan that lives in agent state (`CURRENT_PLAN` global) and is injected into the system prompt each iteration. Persistent across compaction.
- `think(thought)` — a no-op tool that echoes the thought back. Forces externalized reasoning before action.

Reflection (loop-detection that injects a "reconsider" prompt on errors or repeated calls) is deliberately not included — in practice it tends to produce false positives without catching real spirals.

**Code:**
- `agent.py` — Ep 3's agent + the two new tools + plan injection in the system prompt
- `initial/` — `md2html` (the toy codebase) with a test fixture for reference-style markdown links; the fixture fails until the feature is implemented
- `sandbox/` — gitignored, recreated on every run

**Run:**

```bash
python agent.py
```

The agent's task: implement reference-style markdown link support so all tests pass. See `initial/tests/fixtures/reference_style_links.md` and `.html` for the spec by example.

**Full context:**
- `../../README.md` — companion code repo overview
