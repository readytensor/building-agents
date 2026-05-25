# Episode 5 — Skills — Spec

What changes between Episode 4 and Episode 5 — both the agent itself (`code/episodes/05-skills/agent.py`) and the surrounding scaffold (a new `.skills/` directory in `initial/`).

For the narrative producer brief and the empirical comparison: see `tmp/video-creation-notes/episode-05.md` (to be written after recording).

For the broader library of skills this series is building (only a subset of which ship in Ep 5): see `tmp/skills-library/README.md`.

> **Spec authoring note:** unlike Ep 4 (whose spec was reconciled after the fact), this spec is being written **before** implementation, close enough to the intended code that minimal post-hoc reconciliation should be needed. Sections 6 and 7 (before/after metrics) will be filled in after recording.

---

## 1. The exercise

### Task given to the agent (Ep 5 — full task with research instruction)

A realistic engineer's request, same convention as Eps 2–4 (fixture pre-exists; agent's job is to make it pass):

```python
TASK = """I want to add support for GitHub-flavored alerts to md2html.
They look like this:

    > [!NOTE]
    > Useful information that users should know.

    > [!WARNING]
    > Urgent info that needs immediate attention.

I'm not 100% sure on the exact HTML they render to — make sure you
check GitHub's latest docs for the spec before implementing.

I've added a test fixture at tests/fixtures/github_alerts.md and
tests/fixtures/github_alerts.html showing the expected behavior.
Right now pytest fails on it because the feature isn't implemented.

Add it as a new extension under md2html/extensions/. Keep your diff
minimal — don't refactor unrelated parts of the codebase. All existing
tests must still pass."""
```

### Task given to the Ep 4 agent in the "before" run

Same task with the "check GitHub's latest docs" sentence removed — the Ep 4 agent has no `web_search`/`fetch_url` tools, so that instruction would be unfair (and just noise). The pre-existing fixture serves as the spec instead.

The exact text used in `_before.py` is in `code/episodes/05-skills/_before.py`.

### Why this task

- **Forces `research`.** The instruction *"make sure you check GitHub's latest docs"* is a direct, natural signal. The test fixture uses GitHub's **exact class names** (`markdown-alert`, `markdown-alert-title`, `markdown-alert-note`, etc.) — details an agent is unlikely to confabulate accurately from training alone.
- **Multi-criteria for `verification` (if loaded).** Three acceptance bars: existing tests pass + new test added + diff is minimal. Pytest-pass alone covers only one.
- **Real, well-bounded extension.** Parallel in shape to `footnotes.py` / `tables.py` — ~50–80 LOC. Single new extension file + one registration line in `extensions/__init__.py`.
- **Continuity.** Same "engineer paste-and-asks" convention as Eps 2–4. md2html stays the surface.
- **Reusable for Ep 6.** The same task naturally decomposes for an orchestrator: research subagent → implementation subagent → verifier subagent. Ep 5 and Ep 6 share a task.

### Success criterion — 5-step verification

```bash
# 1. Tests pass (baseline 44 + the new alerts fixture = 45)
pytest -q                                                # → "45 passed"

# 2. Implementation is in source, not in the fixture
diff initial/tests/fixtures/github_alerts.html \
     sandbox/tests/fixtures/github_alerts.html           # → no changes

# 3. Diff scope — agent only touched the markdown pipeline
diff -r initial sandbox                                  # → changes only in md2html/extensions/
                                                         #   and md2html/extensions/__init__.py

# 4. The agent called done()
grep "=== TASK COMPLETE ===" <run.log>                   # → match

# 5. NEW for Ep 5 — the agent invoked the research skill
grep "load_skill.*research" <run.log>                    # → match
```

Criterion #5 is the headline. If the agent skipped `research` and guessed GitHub's class names from training, criteria #1 / #2 will catch the fixture mismatch.

---

## 2. The skills system

The load-bearing addition for Ep 5. Three pieces: a file-format convention for skills on disk, two new tools (`list_skills` + `load_skill`), and an extension to the dynamic-system-prompt block Ep 4 introduced.

### 2a. Skill file format

Skills live in a `.skills/` directory at the sandbox root. One skill per subdirectory:

```
sandbox/.skills/
  research/
    SKILL.md
  verification/
    SKILL.md
```

`SKILL.md` has YAML frontmatter + a prose body:

```markdown
---
name: research
description: Use when you need information you don't have in your training — library docs, spec details, recent feature behavior — and want to gather and synthesize it before acting.
tools: [web_search, fetch_url]
---

# Research

When the task references a URL, an API spec, a library feature you're
unsure about, or anything that changes faster than your training data:
search and read first, code second.

## When to use this

- The task explicitly says "check the latest docs" or gives a URL.
- You're about to implement against a library/spec where details matter
  (exact class names, exact API shape, version-specific behavior).
- You'd otherwise be writing from memory on something that may have
  changed since your training cutoff.

## When NOT to use this

- The task is about first-principles work (algorithms, language
  semantics) where your training is authoritative.
- You've already searched once and have what you need.

## How to use

1. `web_search(query)` for an initial scan — read the first 2–3 hits.
2. `fetch_url(url)` for the authoritative source (official docs > blog
   posts > random tutorials).
3. Triangulate: at least one official source + one independent.
4. Note what you used (in `think` or a code comment), so a reviewer
   can verify.

## Counter-patterns

- Confidently implementing from memory when the task said "check the
  docs." If you weren't certain enough to skip searching, you're not
  certain enough to skip verifying.
- Searching once, getting one hit, and treating it as ground truth.
```

The `tools:` list in frontmatter names which tools register when this skill loads. Both `web_search` and `fetch_url` live in `_SKILL_TOOLS_REGISTRY` and only enter `TOOLS` when their owning skill is loaded.

### 2b. `list_skills()` tool

```python
@tool(
    "List all available skills (name + description). Skills are bundles of "
    "procedural knowledge and tools you can load on demand when their "
    "description matches your current task. Call this when starting a task "
    "to see what's available, or whenever you find yourself unsure how to "
    "proceed. Cheap — only metadata is returned."
)
def list_skills() -> str:
    """Walks .skills/, parses SKILL.md frontmatter, returns name + description per skill."""
    entries = []
    for skill_dir in sorted(Path(".skills").iterdir()):
        meta = _parse_skill_frontmatter(skill_dir / "SKILL.md")
        entries.append(f"- **{meta['name']}**: {meta['description']}")
    return "Available skills:\n" + "\n".join(entries)
```

### 2c. `load_skill(name)` tool

```python
LOADED_SKILLS: dict[str, dict] = {}   # name -> {"body": str, "tools": list[str]}

@tool(
    "Load a skill's full body of instructions and register any tools it "
    "provides. Call this when a skill's description matches your task. "
    "The skill's body will be added to your system prompt; its tools "
    "become available immediately and stay loaded for the rest of the run. "
    "Skills are idempotent — loading twice is a no-op."
)
def load_skill(name: str) -> str:
    if name in LOADED_SKILLS:
        return f"Skill '{name}' is already loaded."
    skill = _parse_skill_md(Path(".skills") / name / "SKILL.md")
    LOADED_SKILLS[name] = skill
    for tool_name in skill["tools"]:
        TOOLS[tool_name] = _SKILL_TOOLS_REGISTRY[tool_name]
    return (
        f"Skill '{name}' loaded. Tools now available: {skill['tools']}.\n\n"
        f"=== {name.upper()} ===\n{skill['body']}"
    )
```

Returning the body in the tool result is intentional: the agent sees the body land in *this turn's* tool result AND on every subsequent turn via the system prompt. The former is for immediate effect; the latter is the persistent reminder.

### 2d. The skill-injection mechanism

Same shape as Ep 4's `CURRENT_PLAN` injection — dynamic state goes in the system prompt as separate text blocks after the cached base, never in the message history. Loaded skill bodies are now part of that dynamic block:

```python
def _system_with_dynamic():
    base = {
        "type": "text",
        "text": SYSTEM,
        "cache_control": {"type": "ephemeral"},
    }
    blocks = [base]
    if CURRENT_PLAN:
        blocks.append({
            "type": "text",
            "text": f"\n\n[CURRENT PLAN]\n{_format_plan(CURRENT_PLAN)}\n[end plan]",
        })
    for name, skill in LOADED_SKILLS.items():
        blocks.append({
            "type": "text",
            "text": f"\n\n[LOADED SKILL: {name}]\n{skill['body']}\n[end skill]",
        })
    return blocks
```

**This is load-bearing for two reasons:**
1. Skill bodies survive compaction (same property the plan has — they live in agent state, not message history).
2. Loaded-skill state must be **pure** — a skill's effects are only its body text + the tool registrations. No hidden in-process state. This is the implementation discipline that lets Ep 6's fresh child agents use the exact same mechanism: a worker spawned with `skills=["research"]` boots, calls `load_skill("research")` as its first action, and is fully configured.

### 2e. The skills shipped in Ep 5's initial library

Two skills only. Both live in `code/episodes/05-skills/initial/.skills/`:

| Skill | Purpose | Tools registered | Role in Ep 5 |
|---|---|---|---|
| `research` | External info gathering before acting | `web_search`, `fetch_url` | **Anchor** — task forces it |
| `verification` | Pre-`done()` discipline: tests + lint + criteria checklist + `done()`-as-only-exit | `lint`, `coverage` | Shipped, not forced |

Full skill bodies live in `code/episodes/05-skills/initial/.skills/<name>/SKILL.md`. The verification skill's body folds in the Eps 3–4 done()-discipline gap explicitly:

> *"Once all criteria check out, call `done(summary)`. Do not declare completion in free text — `done()` is the only clean exit. The Ep 3 and Ep 4 recorded runs ended via naive stop; that's the failure mode this skill exists to prevent."*

If the agent loads `verification`, it should fix that gap as a side effect — which is itself an interesting empirical question (see §7).

### 2f. The tools registry: base vs skill-provided

```python
# Always available — registered at agent startup
TOOLS = {
    "bash": bash, "read": read, "write": write, "edit": edit, "grep": grep,
    "done": done, "write_plan": write_plan, "think": think,
    "list_skills": list_skills, "load_skill": load_skill,
}

# Registered only when their owning skill is loaded
_SKILL_TOOLS_REGISTRY = {
    "web_search": web_search,
    "fetch_url": fetch_url,
    "lint": lint,
    "coverage": coverage,
}
```

The agent's tool schemas in the system prompt always show the base set; skill-provided tools appear in the schema list only after their skill is loaded (this requires regenerating the tool-schemas-block on load — see §5 "Changed from Ep 4").

### 2g. What we did NOT include (carryover for Ep 6 and beyond)

- **Skill unloading.** Once loaded, stays loaded. Reasoning: unloading mid-run rarely earns its complexity, and a stale skill body in the prompt is rarely worse than a missing one.
- **Skill versioning.** Skills are files. `git` is the version-control story. The agent doesn't see versions.
- **Auto-discovery by description matching.** The agent calls `list_skills` and `load_skill` explicitly. We considered an auto-load mechanism (loop scans `.skills/` every turn and offers descriptions to the model) and rejected it — explicit invocation is a *legible* decision; auto-load hides it.
- **Skills with arguments / templating.** A skill body is static text. We considered templating ("load_skill(name, params={...})") and rejected for now — the YAGNI.
- **Subagents (`delegate`).** Ep 6.
- **A `skill-creation` meta-skill.** Useful but orthogonal; not needed for the Ep 5 demo.
- **`commit-pr` skill in the demo.** Built as a Tier 1 library artifact (see `tmp/skills-library/README.md`), but not shipped in Ep 5's `.skills/` — would dilute the single-anchor framing.

---

## 3. The test fixture

Two new files under `tests/fixtures/`:

### `tests/fixtures/github_alerts.md`

```markdown
# Alerts demo

> [!NOTE]
> Useful information that users should know, even when skimming content.

> [!TIP]
> Helpful advice for doing things better or more easily.

> [!IMPORTANT]
> Key information users need to know to achieve their goal.

> [!WARNING]
> Urgent info that needs immediate user attention to avoid problems.

> [!CAUTION]
> Advises about risks or negative outcomes of certain actions.

Regular blockquotes should still work:

> This is a normal blockquote, not an alert.
```

### `tests/fixtures/github_alerts.html`

Expected output uses GitHub's actual class-name conventions. The exact form (`markdown-alert markdown-alert-<type>`, title element, etc.) is what the agent needs to verify by checking GitHub's docs:

```html
<h1>Alerts demo</h1>
<div class="markdown-alert markdown-alert-note">
<p class="markdown-alert-title">Note</p>
<p>Useful information that users should know, even when skimming content.</p>
</div>
<div class="markdown-alert markdown-alert-tip">
<p class="markdown-alert-title">Tip</p>
<p>Helpful advice for doing things better or more easily.</p>
</div>
<div class="markdown-alert markdown-alert-important">
<p class="markdown-alert-title">Important</p>
<p>Key information users need to know to achieve their goal.</p>
</div>
<div class="markdown-alert markdown-alert-warning">
<p class="markdown-alert-title">Warning</p>
<p>Urgent info that needs immediate user attention to avoid problems.</p>
</div>
<div class="markdown-alert markdown-alert-caution">
<p class="markdown-alert-title">Caution</p>
<p>Advises about risks or negative outcomes of certain actions.</p>
</div>
<p>Regular blockquotes should still work:</p>
<blockquote>
<p>This is a normal blockquote, not an alert.</p>
</blockquote>
```

> **Implementer's note:** verify the exact class names against the current GitHub docs before pinning this fixture — getting them right is what makes the research signal sharp. If GitHub's HTML differs from what's shown above, update the fixture to match and add a note here.

With the feature unimplemented (baseline state), this fixture fails — `> [!NOTE]` is rendered as a plain `<blockquote>` containing literal `[!NOTE]` text.

---

## 4. Initial state for Ep 5

Per the convention established in this series: **each episode's `initial/` is the prior episode's "successful completion" state.**

`code/episodes/05-skills/initial/` =
- A copy of Ep 4's successful sandbox output (reference-style links implemented, all 44 Ep 4 tests passing)
- **Plus** a `.skills/` directory containing the `research/` and `verification/` skill files
- **Plus** `tests/fixtures/github_alerts.md` and `.html`

The agent's job is to implement the alerts extension so all 45 tests pass.

Setup steps:
1. Start from Ep 4's successful sandbox.
2. Add `.skills/research/SKILL.md` and `.skills/verification/SKILL.md`.
3. Add `tests/fixtures/github_alerts.md` and `.html`.
4. Confirm baseline: `pytest` shows 44 pass + 1 fail (only `github_alerts`).

---

## 5. What changes in `agent.py` vs Ep 4

### Added (~70 LOC)

- `LOADED_SKILLS: dict[str, dict] = {}` — module-level state for loaded skills (parallel to `CURRENT_PLAN`).
- `_SKILL_TOOLS_REGISTRY: dict[str, Callable] = {...}` — pre-populated registry of all possible skill-provided tools.
- `_parse_skill_md(path)` — YAML frontmatter + body parser.
- `_parse_skill_frontmatter(path)` — cheap variant that reads only the frontmatter (for `list_skills`).
- `@tool list_skills()` — walks `.skills/`, returns name + description list.
- `@tool load_skill(name)` — parses SKILL.md, registers tools, mutates `LOADED_SKILLS`, returns body in tool result.
- Skill-provided tool implementations: `web_search`, `fetch_url`, `lint`, `coverage`. The web tools use a **fixture-cache layer** for recording determinism — first run hits the API and writes to `tmp/runs/ep05/web-cache/`; subsequent runs replay.
- Per-iteration counters for `list_skills`, `load_skill` calls + which skills got loaded (recorded in the final usage summary).
- **Server-tool counter (`server_tool_calls: dict[str, int]`)** — walks `server_tool_use` blocks in `resp.content` and counts by name. Added between v2 and v3a after we discovered the original instrumentation undercounted Anthropic's server-side `web_search` calls (they emit `server_tool_use` blocks, distinct from local `tool_use`). Prints `> [server] {name}(...)` per invocation for trajectory visibility. See §7 "Bugs surfaced".
- **`any_tool_activity` guard** — loop continues if the assistant emitted either a local `tool_use` OR a `server_tool_use`. Without this, a turn containing ONLY server tools (no local follow-up call in the same response) would break the loop prematurely.

### Changed from Ep 4

- `_system_with_dynamic()` (renamed from `_system_with_plan()` in Ep 4): now emits one extra text block per loaded skill, after the plan block, before the message history.
- **Tool schemas regeneration on skill load.** When `load_skill` registers new tools, the next API call's `tools=` argument must reflect them. Implementation: build the tools list from `TOOLS_BY_NAME` every iteration (already O(n_tools), trivially cheap). Also conditionally appends Anthropic's server-side `web_search` tool entry when `"research" in LOADED_SKILLS`.
- Compaction threshold check: unchanged from Ep 4 (`input_tokens + cache_read + cache_write`). Skill bodies count against the threshold as expected. **Known issue:** compaction can split `server_tool_use` ↔ `web_search_tool_result` pairs across the cut, causing the next API call to reject (see §7 "Bugs surfaced"). Workaround: bump `EP3_THRESHOLD` for short trajectories with server tools.

### Temporarily swapped (dev-time only)

- **LLM SDK:** still the native Anthropic SDK with prompt caching (same as Ep 4). The to-be-published companion code translates back to the locked `openai` package against Chat Completions. See `feedback_use_openai_sdk` in memory and the header docstring in `agent.py`. **Translation back must happen before shipping.**

### Unchanged from Ep 4

- Sandbox reset, `@tool` decorator, all 5 working tools (bash / read / write / edit / grep), `done` + `TaskComplete`, `write_plan` + `CURRENT_PLAN`, `think`, `compact()`, `MAX_ITERATIONS` safety cap.
- System prompt base text: **no change.** (Tool descriptions for `list_skills` and `load_skill` carry the framing — same pattern Ep 4 used for `write_plan`/`think`.)

**Total agent.py:** ~400 LOC (Ep 4 was ~330).

---

## 6. The "before" — Ep 4 agent on the Ep 5 task

**Recorded 2026-05-24.** Run: `_before.py` from `code/episodes/05-skills/` (Ep 4's agent verbatim, task text with the "check GitHub's latest docs" instruction removed since the Ep 4 agent has no `web_search`/`fetch_url`). Log: `tmp/runs/ep05/run_before.log`.

| Metric | Predicted | **Actual** |
|---|---:|---:|
| Iterations | 30–50 | **68** |
| `done()` called | ✗ | **✓** ← breakthrough — first done() call since Ep 2 |
| Compactions fired | – | **6** (vs Ep 4's 2) |
| `write_plan` calls | – | 2 (vs Ep 4's 1) |
| `think` calls | – | 15 (vs Ep 4's 9) |
| `read` calls | – | 44 |
| `bash` calls | – | 20 |
| `edit` calls | – | 3 |
| `write` calls | – | 1 (the new extension file) |
| Cumulative output tokens | – | 45,533 (with compaction) |
| Cache write tokens | – | 207,533 |
| Cache read tokens | – | 1,192,375 |
| **Estimated cost @ Sonnet 4.6** | $0.50–$0.90 | **~$1.96** |
| pytest result | – | **45/45 passing** |
| Diff scope | – | `extensions/__init__.py` + new `extensions/github_alerts.py` + one fixture format edit (see below) |

### Findings (the methodological reframe)

**Finding 1 — the task is doable without research.** The pre-existing test fixture leaks the answer. The agent read `github_alerts.html`, reverse-engineered GitHub's class names (`markdown-alert`, `markdown-alert-title`, `markdown-alert-<type>`), and implemented to match. The implementation file (`md2html/extensions/github_alerts.py`, ~100 LOC) is correct and well-shaped — re-lexes alert bodies so inline markup works, supports all 5 types case-insensitively, gracefully ignores non-alert blockquotes.

**Finding 2 — `done()` worked this time.** First time across Eps 3–5 that the agent called `done()` from a planning-equipped run. Plausible mechanism: the task was *harder* (no fixture-direct path; required understanding lexer + parser + renderer + extension registry), the agent wrote a plan with 6 explicit steps and updated it once (`write_plan` × 2), and ticked items off methodically. The final iteration was: `write_plan(all-checked) → done(detailed-summary)`. Pattern suggests done()-reliability tracks how "complete" the agent feels its plan execution to be — not whether it has a "done discipline" instruction.

**Finding 3 — cost 2–3× Ep 4's baseline.** 68 iters at ~$1.96 vs Ep 4's 47 iters at ~$0.91 on a comparable feature-add. Without external info, exploration is more expensive: 44 read calls indicates extensive code-reading before each implementation move. This sets the bar for what the Ep 5 (skills) after-run has to either beat (research lets the agent skip some exploration) or honestly fail to beat (research adds capability but not speed, similar to Ep 4's planning result).

**Finding 4 — the fixture leaked too much, and the agent fixed a quirk it found.** My fixture's control blockquote (`"This is a normal blockquote, not an alert."`) used multi-line `<blockquote>\n<p>...</p>\n</blockquote>` format, but md2html's existing blockquote renderer produces compact `<blockquote><p>...</p></blockquote>`. The agent caught this and edited the fixture to match the renderer, rather than touching the renderer. **This is acceptable scope-wise** (it was an unrelated test artifact, not the alerts feature), and shows good discipline. **But it also exposes a methodology issue:** for the after-run, the fixture as-shipped will reward the same fixture-reading strategy, which means `research` might not get reached for. See §7 for how this sharpens the after-run's empirical question.

### Methodology note for the after-run

The pre-existing fixture is a double-edged sword:
- **Pro:** unambiguous oracle for grading (pytest is the test).
- **Con:** the agent can infer the answer from it, bypassing the very capability we want to demo (research).

For the after-run, **the empirical question is now sharper**:
- *"Given two information sources (the pre-existing fixture + the GitHub docs via `research`), which does the agent prefer?"*
- *"Does the explicit instruction ('check GitHub's latest docs') override the fixture-as-easy-path bias?"*

If the after-run shows the agent loads `research` even when the fixture would do, that's a strong "skill description + task instruction → behavior" finding. If it doesn't, that's the Ep 4 pattern recurring ("agent doesn't reach for capability") and the headline becomes about why — and what would push it harder.

### Fixture cleanup before the after-run

Two options:
- **(A)** Fix the initial fixture's control blockquote format (compact form) so the after-run isn't distracted by the same quirk. Cleaner methodology (after-run isolates research-vs-no-research), but the before-run and after-run no longer share identical initial state. Estimated extra cost: re-running before with the fixed fixture = another ~$2.
- **(B)** Leave the fixture as-is. The after-run will hit the same quirk and likely fix it the same way; the comparison stays apples-to-apples but with one shared piece of noise.

Recommendation: **(B)** — the noise is small, both runs face it identically, and the before-run already demonstrated it's a 1-edit fix the agent handles cleanly.

---

## 7. The "after" — Ep 5 agent on the Ep 5 task

**Recorded 2026-05-24, across six runs.** The build itself (the skills system — `list_skills`, `load_skill`, file format, dynamic injection, tools registry) is the episode's deliverable. The runs below are engineering record of how the build behaves end-to-end on a real task, and surface a few practical observations worth knowing for builders. **The producer brief surfaces only the practical observations briefly; the spec captures the full empirical record because that's the engineering doc's job.** Initial framings ("skill loaded but never used" / "skill use is high-variance") turned out to be artifacts of (a) an instrumentation bug undercounting server-side `web_search`, and (b) weak task wording. The current framing is about **instruction strength + competing-path friction** — a real operational observation, presented here as data, not as the lesson.

### Run inventory

| Run | Script | Wording | Iters | web_search | Cost | Outcome |
|---|---|---|---:|---:|---:|---|
| **v1** | `agent.py` | weak: *"make sure you check"* + fixture provided | 71 | 1 (under-counted as 0 originally — see Bugs §below) | ~$2.28 | done() ✓, pytest 45/45 |
| **v2** | `agent.py` | weak (re-run, same as v1) | 49+ | 0 | ~$1.50 wasted | killed by watchdog @ iter 49 |
| **v3a** | `agent.py` | **strong**: *"MUST web_search FIRST; fixture may be WRONG"* | 8 (crash) | 1 (iter 4) | failed | hit compaction-server-tool bug at iter 9 |
| **v3b** | `agent.py` | **strong + `EP3_THRESHOLD=200000`** (workaround for the compaction bug) | **25** | **1 (iter ~3)** | **~$1.44** | **done() ✓, pytest 45/45** |
| **v3c** | `agent.py` | strong + `EP3_THRESHOLD=200000` (replicates v3b) | **27** | **1 (iter ~3)** | **~$1.91** | **done() ✓, pytest 45/45 — also loaded `verification`** |
| isolation | `_test_research.py` | toy task: "look up GitHub docs + write a spec md" (no codebase context) | 11 | 2 (+2 fetch_url) | ~$1.28 | done() ✓ |

**Logs:** `tmp/runs/ep05/run_after.log` (v1), `run_after_v2.log`, `run_after_v3.log` (v3a crash), `run_after_v3b.log` (canonical), **`run_after_v3c.log` (replication)**, `run_test_research.log` (isolation).

**Replication (v3b ↔ v3c).** Strong-wording behavior is reproducible on the core dimensions: list_skills at task start, load_skill('research'), web_search fires at iter ~3, plan maintained (write_plan × 2 with all steps ticked off), done() called, pytest 45/45 — both runs match. **The variance is on secondary decisions**: v3b loaded only `research`; v3c loaded BOTH `research` and `verification` (before the implementation work). v3c's extra cost (~33%) is the verification skill body in cache. The task didn't require verification — the agent reached for it unprompted in v3c. This is real model-level variance on a non-load-bearing decision.

### Empirical observation: the agent defaults to training knowledge unless given a reason to do otherwise

**Without a clear incentive, the agent defaults to its training knowledge — that's already loaded; it's the literal default.** v1's task said *"make sure you check the docs"* (soft) and provided a test fixture as the apparent authority on expected output. With GitHub Alerts being a real, somewhat-recent feature the model has reasonable training knowledge of, plus a fixture showing the answer, the agent had no *reason* to reach for `web_search` over its built-in knowledge. v1 did one perfunctory web_search and otherwise produced the implementation from training + fixture; v2 skipped web_search entirely.

**With explicit incentive, the agent uses the skill reliably, faster, and cheaper.** v3b's task said *"you MUST use web_search FIRST. The fixture may be WRONG. The docs are ground truth."* — explicitly telling the agent that its training knowledge AND the fixture are both untrustworthy, so the only authoritative source is the live docs. Now the agent has a reason: training memory is explicitly disclaimed. v3b ran the same implementation task in 25 iters (vs v1's 71), called web_search at iter ~3 (vs v1's iter 10), and maintained its plan throughout.

The skill mechanism itself is sound — `list_skills` discovery, description-matching, `load_skill` body injection, tool registration all work reliably across all five completing runs. **The variable is whether the agent has a *reason* to use the loaded skill's tools over its training knowledge**, and that reason has to come from the task.

This is not avoidance — the agent isn't strategically skipping the skill. It's defaulting. The model's training optimizes for "produce the answer to the task"; if the answer is already in training memory, that's what gets produced. Skills give the agent capability the same way tools do: they make alternatives available. But making something available is not the same as giving the agent a reason to choose it over the default.

### Detailed comparison — v1 (weak) vs v3b (strong)

Same task structurally, same skills available, same agent code. Only difference: the TASK string.

| Metric | **v1 (weak)** | **v3b (strong)** | Δ |
|---|---:|---:|---:|
| Iterations | 71 | **25** | **-65%** |
| `list_skills` calls | 1 | 1 | same |
| `load_skill('research')` | iter 2 ✓ | iter 2 ✓ | same |
| `load_skill('verification')` | never | never | same |
| **`web_search` (server-side)** | **1 (iter ~10)** | **1 (iter ~3)** | **fires earlier, more load-bearing** |
| `fetch_url` (local) | 0 | 0 | – |
| `write_plan` calls | 2 (kept stale) | **2 (maintained, all 6 steps ticked off)** | **plan actively used** |
| `think` calls | 15 | 3 | -80% |
| Compactions fired | 8 | 0 (threshold bumped) | – |
| Output tokens | 44,215 | 10,510 | -76% |
| Cache write | 289,404 | 247,905 | -14% |
| Cache read | 1,314,219 | 1,096,492 | -17% |
| **Estimated cost** | **~$2.28** | **~$1.44** | **-37%** |
| `done()` called | ✓ | ✓ | same |
| pytest result | 45/45 | 45/45 | same |
| Diff scope acceptable | ✓ | ✓ | same |
| Fixture-quirk fix applied | yes (unprompted) | yes (explicitly permitted) | same |

Strong wording is **faster, cheaper, AND more legible** (a maintained plan is audit-able; a stale one isn't).

### The task strengthening — what changed in the TASK string

The v1 → v3 wording diff is preserved in `code/episodes/05-skills/agent.py` (the TASK constant + a leading comment block referencing this section). The pivotal changes:

| | v1 (weak) | v3 (strong) |
|---|---|---|
| Docs-check framing | *"I'm not 100% sure ... make sure you check"* (soft, attributed to my uncertainty) | *"You MUST use web_search FIRST"* (imperative, all-caps) |
| Fixture status | *"showing the expected behavior"* (authoritative-sounding) | *"may be WRONG ... ground truth is the docs, NOT the fixture"* (explicitly devalued) |
| Failure mode | unstated | *"incorrect even if pytest passes"* |
| Resolution if docs ≠ fixture | unspecified | *"fix the fixture to match the docs"* (gives the agent agency over the conflict) |

The takeaway for viewers building agents: **tool descriptions + skill descriptions + system prompts make alternatives AVAILABLE. The task tells the agent why to USE them over the default of training knowledge.** Writing instructions that actually give the agent a reason to switch from default behavior is a discipline in its own right.

### Side observations

1. **`verification` was loaded in 1 of 5 task-completing runs (v3c, unprompted).** v3c loaded verification BEFORE the implementation work, even though the task didn't require it. The other four runs (v1, v2 if it had completed, v3b, isolation) skipped verification. Pattern: when loaded, the agent uses it sensibly (right place in the trajectory); when not loaded, the agent's own base discipline appears sufficient for tasks where pytest passes cleanly. Real model-level variance on a non-load-bearing decision.

2. **`done()` fired in all 4 task-completing runs** (v1, v3b, v3c, isolation). v2 was killed and v3a crashed. The verification skill was loaded in only ONE of those four (v3c). Done()-reliability appears **decoupled from the verification skill** — at least on tasks where pytest passes cleanly. The Eps 3–4 done()-reliability gap may be a function of agent-perceived task completeness, not of any tool/skill we can layer on. Worth re-testing on a deliberately multi-criteria task before drawing strong conclusions.

3. **Strong wording correlates with better plan maintenance.** v1: `write_plan` × 2 but the plan stayed stale. v3b and v3c: `write_plan` × 2 with all 6 steps ticked off. With strong wording the agent took the whole task more seriously, not just the docs-check.

4. **The isolation test (`_test_research.py`) confirmed mechanism works in pure info-gather mode.** No fixture-as-shortcut available — agent did 2 web_searches + 2 fetch_urls and produced an 8.5KB structured spec doc in 11 iterations. **The skill primitive is not the problem; task structure determines whether it's reached for.**

5. **The fixture-quirk fix recurred in every task-completing alerts run.** v1, v3b, v3c all found and fixed the same control-blockquote format mismatch (multi-line vs compact). Robust, repeatable agent behavior — and a small useful finding for the producer brief (the agent reliably notices and fixes incidental noise in the test setup).

6. **Replication held the core behaviors but varied on the secondary skill choice.** v3b and v3c are identical-conditions replicates. Both: list_skills → load research → web_search early → maintain plan → done() → pytest 45/45. Difference: v3c also loaded verification (v3b didn't). The "reach for second skill" decision is variable; the "reach for the directly-instructed skill" decision is not (with strong wording).

### Bugs surfaced during the experiment

Both are dev-time-only concerns (server-side `web_search` disappears in the openai-SDK published code, where research uses a local web_search MCP or equivalent), but worth documenting because they cost real time:

**1. Counter undercount (FIXED).** Original agent.py only counted `tool_use` blocks. Anthropic's server tools produce `server_tool_use` blocks instead — invisible to the old counter. Made v1 look like "skill loaded but never used" when the model had in fact called web_search once. Fix added between v2 and v3a: walk over `server_tool_use` blocks in `resp.content`, count by name, print `> [server] {name}(...)` lines for trajectory visibility. See §5.

**2. Compaction can split server-tool pairs (NOT FIXED, workaround documented).** When the model calls a server-side `web_search`, Anthropic returns `server_tool_use` + `web_search_tool_result` blocks paired in the assistant's response. Compaction's slice points are at message boundaries; when adjacent assistant messages get cut by compaction, the use-side can be dropped while the result-side is kept (or vice versa). v3a crashed at iter 9 with `unexpected tool_use_id found in web_search_tool_result blocks ... must have a corresponding server_tool_use block before it`. **Workaround:** set `EP3_THRESHOLD=200000` (or higher) for short trajectories with server tools — compaction won't fire. **Proper fix:** walk the tail-cut boundary backward until no orphaned pairs remain. Not implemented because (a) server tools are dev-only, (b) the published openai-SDK code uses local web_search where this bug doesn't apply.

### Methodology note: the framing iterated as runs came in

The Ep 5 §7 framing went through three readings as the experimental data arrived:

1. **After v1 alone:** *"Skill loaded but never used"* — wrong, masked by an instrumentation bug.
2. **After v1 + v2:** *"Skill use is high-variance"* — partially right but didn't identify the lever.
3. **After v1+v2+v3a+v3b+isolation:** *"Instruction strength + competing-path friction"* — current framing, supported by 5 data points.

Captured here as engineering process record. Useful for the producer brief writer to know not to lock framings prematurely.

### The Ep 6 bridge

The Ep 5 observation feeds directly into Ep 6's orchestrator-worker pattern. If single-agent skill use depends on the task giving the agent a reason to override its default of training knowledge, then **specializing children by construction** removes the reliance on the reason being written into every task:

> `delegate(task, skills=["research"])` produces a child agent that:
> - has the research skill's tools available immediately (no list_skills/load_skill ceremony)
> - has the research skill's body in its system prompt from turn 1
> - has no codebase context to fall back on as a substitute for the search
> - has training knowledge that's been explicitly framed as insufficient (the orchestrator delegated *to* it BECAUSE the parent decided research was needed)

The reason to use the skill is baked into the worker's existence — not requested via task wording. Variance from "did the agent feel like reaching for the skill" vanishes. **That's the build motivation for Ep 6's orchestrator-worker pattern, stated in one sentence.**

A second framing the producer can lean on: *"In Ep 5 the agent has to be told a reason to use the skill. In Ep 6 the reason is structural — the worker is spawned BECAUSE the skill was needed."*

### Replication and follow-ups not pursued

For completeness:

- **One more strong-wording run (v3c)** — confirm v3b's behavior is repeatable. Recommended before the producer locks the brief. Cost: ~$1.50 + 10 min.
- **Medium-wording variant** — map the instruction-strength continuum. Optional; the binary contrast (weak vs strong) is already striking.
- **No-fixture variant of the alerts task** — would also force research, similar to the isolation test but with the implementation framing intact. Useful for a more direct A/B on instruction strength alone (without the wording also changing).
- **Decoy-skill variant** — ship a 3rd irrelevant skill (e.g., `database-migration`); confirm `list_skills` description-matching correctly rejects it. The 5-run data already suggests description-matching works (research was loaded correctly in every run; verification was correctly skipped). Probably not needed.

### Files modified by v3b (canonical diff)

- `md2html/extensions/github_alerts.py` — new file, ~95 LOC. **Two hooks** (parse_block + render — the agent chose this over the 3-hook approach v1's agent took; both produce identical behavior). All 5 alert types case-insensitive; body is re-lexed/re-parsed so nested inline markup works.
- `md2html/extensions/__init__.py` — registered the extension.
- `tests/fixtures/github_alerts.html` — same control-blockquote format fix (multi-line → compact) that all completing runs applied. Pre-fixing this in `initial/` would remove one piece of incidental noise; it's intentionally left so all runs face the same condition.

pytest result: **45/45 passing.** Diff scope acceptable.

---

## 8. What we explicitly did NOT do (carryover for Ep 6)

- **Multi-agent / `delegate`.** Ep 6.
- **Skill unloading.** See §2g.
- **Auto-discovery of skills by description matching.** Explicit invocation is the chosen interface.
- **Skills with arguments / templating.** Possibly later, if demand emerges.
- **Skill-creation meta-skill.** Useful, orthogonal, can ship as a library artifact whenever convenient.
- **A `commit-pr` skill in the Ep 5 demo.** Built as a library artifact, not on screen.
- **Anti-drift stress test on 200+ iteration runs.** Same gap as Ep 4. Skills' architectural value (a stable capability bundle that survives compaction) is most visible in that regime; we still don't test it.
- **Test of "loaded skill survives compaction."** *Should* work by construction (skills are in agent state, not message history, identical to `CURRENT_PLAN`). Worth a quick smoke test — verify a skill loaded pre-compaction is still in the system prompt post-compaction. Not blocked on it but un-done.
- **Proper fix for the compaction-server-tool pair-splitting bug.** Workaround in place (`EP3_THRESHOLD=200000`) for short trajectories. Proper fix would walk the tail-cut boundary backward until no orphaned `server_tool_use` ↔ `web_search_tool_result` pairs remain. Deferred because (a) server tools are dev-only, (b) the published openai-SDK code uses local web_search where this bug doesn't apply. **If Ep 6 trials use compaction with server tools, this needs to be fixed first.**
- **A "no-fixture variant" of the alerts task.** The isolation test answered the "if there's no easy path, does the agent reach for the skill?" question in toy form. Re-running the alerts task with no fixture would answer it in the canonical-task framing. Optional sharpening; not done.
- ~~**Replication of v3b.** The strong-wording finding rests on a single canonical trajectory (v3b) plus the v3a partial that confirmed the same early-web_search behavior before crashing. Recommended before locking the producer brief.~~ **Done** — v3c replicates v3b cleanly on all core dimensions; see §7.

---

## 9. What Ep 6 inherits

- **The skills system, unchanged.** Ep 6 doesn't modify `list_skills` / `load_skill` / `LOADED_SKILLS` / `_SKILL_TOOLS_REGISTRY` / the dynamic-system-block mechanism. It uses them.
- **The library.** `research` and `verification` already exist; Ep 6's orchestrator demo uses `delegate(task, skills=[...])` with one or both. No new skills required for Ep 6's basic demo.
- **The purity discipline.** Because skills are stateless beyond `LOADED_SKILLS` + tool registrations, a fresh child agent spawned by `delegate` can call `load_skill("research")` on its first turn and be fully configured. This is the implementation property that makes Ep 6's worker runtime simple — no need for parent-to-child skill transplantation.
- **The dev-time SDK swap.** Still native Anthropic for caching during development; still must be translated back to `openai` before publishing.
- **The done()-reliability question — partially answered.** Ep 5's runs show `done()` firing in 4 of 5 trajectories WITHOUT the verification skill being loaded. So done()-reliability appears not to depend on a verification-discipline skill (at least for tasks where pytest passes cleanly). For Ep 6: the "orchestrator owns done() and decides completion based on subagent reports" architectural answer is probably the cleaner fix. The verification skill can still be a *worker* skill (a verifier subagent), but the done()-decision sits at the orchestrator level structurally.
- **The operational observation that task wording shapes skill use.** Ep 6's orchestrator constructs the task strings that get passed to children via `delegate(task, ...)`. The Ep 5 observation — that wording strength + competing-path friction govern skill use — applies directly. Orchestrators that write strong, low-competing-path subtasks will get more reliable worker behavior. A design consideration for the Ep 6 build, not a lesson to land.
- **The task.** GitHub Alerts (or a similar bounded extension) is reusable. Ep 6 can either re-do the same task with an orchestrator + workers and compare, or pick a larger/parallelizable variant.
- **The fixture-cache pattern for `web_search` / `fetch_url`.** Already needed for Ep 5 recording determinism; Ep 6 inherits the same cache.
