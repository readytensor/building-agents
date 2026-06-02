# Episode 5 — Skills

**Concept:** let the agent reach beyond its fixed toolkit by *discovering and loading skills on demand*, instead of carrying every possible tool in the system prompt on every call.

**This episode's additions on top of Ep 4:**
- `list_skills()` — returns the name + one-line description of each available skill (cheap; always present).
- `load_skill(name)` — parses `.skills/<name>/SKILL.md`, appends its body to the dynamic system-prompt block, and registers any tools the skill provides.
- A `.skills/<name>/SKILL.md` file format (YAML frontmatter + markdown body).
- A skill-provided tools registry, so a skill's tools only enter the agent's toolkit once that skill is loaded.
- Extends Ep 4's dynamic system-prompt mechanism to also carry loaded-skill bodies.

Completion is unchanged from earlier episodes — the **natural stop** (the loop ends when the model stops calling tools). Rigorous, test-based completion is available as the `verification` skill (run the tests before finishing); there is no separate "done" tool.

**Code:**
- `agent.py` — the agent loop + the skills system (`list_skills`, `load_skill`, the `SKILL.md` parser, loaded-skill state, and the skill-provided tools registry)
- `initial/.skills/` — the skill library shipped to the agent:
  - `research/SKILL.md` — web research (`web_search` + `fetch_url`)
  - `verification/SKILL.md` — verify-before-finishing discipline (runs the tests / lint + coverage)
- `initial/` — `md2html` (the toy codebase) with a test fixture for GitHub-flavored alerts; the fixture fails until the feature is implemented
- `sandbox/` — gitignored, recreated on every run

**Run:**

```bash
python agent.py
```

The agent's task: add GitHub-flavored alerts (`> [!NOTE]`, `> [!WARNING]`, etc.) to `md2html`. The task points the agent at GitHub's own docs for the spec, which is what gives it a reason to discover and load the `research` skill. See `initial/tests/fixtures/github_alerts.md` and `.html` for the spec by example.

**Full context:**
- `../../README.md` — companion code repo overview
