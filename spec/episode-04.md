# Episode 4 — Planning + Think — Spec

What changed between Episode 3 and Episode 4 — both the agent itself (`code/episodes/04-planning-reasoning/agent.py`) and the toy codebase state in `code/episodes/04-planning-reasoning/initial/`.

For the narrative producer brief and the empirical comparison: see `tmp/video-creation-notes/episode-04.md`.

> **Spec lineage note:** an earlier draft of this spec described a tables-in-lists bug-fix task and a reflection-loop tool. Implementation pivoted away from both. The task became reference-style markdown link support (feature-add, not bug-fix), and reflection was dropped after trial runs showed loop-detection produced mostly false positives without catching real spirals. This spec now matches what was built and recorded.

---

## 1. The exercise

### Task given to the agent

A realistic engineer's request — paste-and-ask, same convention as Eps 2 and 3:

```python
TASK = """I want to add support for reference-style links to our markdown
library. They look like this:

    Here is a [link][myref] in text.

    [myref]: https://example.com "Optional title"

The link definitions (the `[id]: url "title"` lines) get collected from
the document, and inline `[text][id]` references resolve to <a> elements
using those URLs. The definition lines themselves should NOT appear in
the rendered output.

I've added a test fixture at tests/fixtures/reference_style_links.md and
tests/fixtures/reference_style_links.html showing the expected behavior.
Right now pytest fails on it because the feature isn't implemented.

Can you add reference-style links? Make sure all other tests still pass."""
```

### Why this task (not a bug fix)

- **Multi-step structure makes planning's value plausible *a priori*.** Implementation touches lexer (detect `[id]:` definition lines), parser inline pass (recognize `[text][id]` references with deferred resolution), renderer (emit `<a>` from the resolved target), and the extension registry. Each step depends on understanding prior pipeline stages. This is the shape of work where a human would naturally plan.
- **Genuine feature add, not a bug fix.** Bug fixes are short and reactive — they don't reward forward thinking. Feature adds do. The right shape of work to *fairly test* "does planning help?"
- **Real verification target.** The test fixture pair is the unambiguous oracle. No subjective evaluation of "did it implement the feature."

### Success criterion — 4-step verification

```bash
# 1. Tests pass (baseline 43 + the new fixture)
pytest -q                                                # → "44 passed"

# 2. The implementation is in source, not in the fixture
diff initial/tests/fixtures/reference_style_links.html \
     sandbox/tests/fixtures/reference_style_links.html   # → no changes

# 3. Diff scope — agent only touched the markdown pipeline
diff -r initial sandbox                                  # → changes only in md2html/extensions/,
                                                         #   __init__.py, optionally renderer

# 4. The agent called done()
grep "=== TASK COMPLETE ===" <run.log>                   # → match
```

**Recorded reality:** criterion 4 failed in **both** recorded runs (Ep 3 baseline AND Ep 4 with planning). Both ended via naive stop with a free-text "I'm done" response. The done()-reliability gap is documented as the bridge to Ep 5 — see the producer brief and the auto-memory at `feedback_done_reliability_overdue.md`.

---

## 2. The two new tools

### 2a. `write_plan(steps)` — structured plan tool

A Claude Code TodoWrite-equivalent. State-bearing.

```python
CURRENT_PLAN: list[dict] = []   # module-level state; mutated by the tool

@tool(
    "Set or update your working plan for a MULTI-STEP TASK. Pass the FULL "
    "current state of the plan as a list of steps. Each step is either a "
    "string OR a dict with 'content' (string) and 'status' (one of "
    "'pending', 'in_progress', 'completed'). Call this at the start of a "
    "multi-step task and again whenever you complete a step or revise your "
    "approach. The plan is always visible to you in subsequent iterations. "
    "USE THIS FOR: tracking progress through multiple distinct subtasks. "
    "NOT FOR: in-the-moment reasoning about a single hard problem — for that, "
    "use the `think` tool."
)
def write_plan(steps) -> str:
    # defensive parsing: model sometimes passes a JSON-encoded string
    # instead of a list, or strings inside the list instead of dicts.
    # Recover gracefully — see implementation in agent.py.
    ...
```

### 2b. `think(thought)` — externalized-reasoning tool

A no-op echo. Stateless. Forces the model to write a reasoning paragraph before the next action.

```python
@tool(
    "Externalize your reasoning about a hard problem or decision. Pass a "
    "thought as a string; it is echoed back unchanged. The act of writing "
    "the thought out forces explicit reasoning before action. "
    "USE THIS FOR: weighing alternative approaches before choosing one, "
    "reasoning through a tricky edge case, untangling a confusing problem. "
    "NOT FOR: tracking multi-step task progress — for that, use `write_plan`."
)
def think(thought: str) -> str:
    return thought
```

**The two-tool framing matters.** Their `@tool` descriptions are doing real work — pointing the model to the right tool for the right mode. `write_plan` for *state*; `think` for *scratchpad*. We confirmed the distinction holds empirically — see recorded run F: `write_plan` fired exactly once at the start; `think` fired 9 times across the run for in-the-moment judgments.

### 2c. The plan-injection mechanism (load-bearing)

`CURRENT_PLAN` is injected into the **system prompt** each call, as a SEPARATE text block appended AFTER the cached base system text:

```python
def _system_cached():
    base = {"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}
    if CURRENT_PLAN:
        plan_block = {
            "type": "text",
            "text": f"\n\n[CURRENT PLAN]\n{_format_plan(CURRENT_PLAN)}\n[end plan]",
        }
        return [base, plan_block]
    return [base]
```

**This placement is load-bearing.** An earlier implementation injected the plan into the message list (appended as a text block to the last user message of each call). That broke prompt caching catastrophically: the "last user message" position changes every iter, so the plan text effectively moves each turn, invalidating any cached entry at that position. Caching costs went *up*, not down, vs no caching at all (1.25× write premium paid per iter with no read benefit).

Putting the plan in system instead keeps the message prefix byte-stable, lets the static-vs-dynamic split inside system handle plan changes cleanly (base text cached forever; plan addendum re-pays only when the plan changes), and survives compaction. **For Ep 5 and any future agent-loop work in this series: dynamic per-call state goes in system, not messages.** See the auto-memory at `feedback_prompt_cache_prefix_stability.md`.

### 2d. What we did NOT add (reflection)

The original spec included a loop-based reflection mechanism — the loop detects "tool error" or "repeated tool call with same args" and injects a `[REFLECT] ...` user message to force the model to step back and reconsider.

We built it, ran trials, and dropped it. Findings:
- **False positives dominated.** Legitimate verification reruns (`bash("pytest")` called repeatedly as the agent makes progress) were mis-flagged as spirals.
- **Real spirals weren't caught.** The agent's failure mode on the recorded runs wasn't repeated tool calls — it was over-confident summarization (the Ep 3 "hallucinated success" pattern in a different form).
- **Added noise without value.** Net cost per run went up; trajectory quality didn't measurably improve.

The episode acknowledges reflection as a cut, but doesn't show or build it. The remaining two-tool framing (`write_plan` + `think`) is cleaner pedagogically and matches what the recorded runs actually used.

---

## 3. The test fixture

Two new files under `tests/fixtures/`:

### `tests/fixtures/reference_style_links.md`

```markdown
This is a [paragraph][example] with a reference-style link.

Here is [another link][example] using the same reference.

And one [more][different] using a different reference.

The references themselves don't appear in the rendered output.

[example]: https://example.com "Example site"
[different]: https://example.org/foo
```

### `tests/fixtures/reference_style_links.html`

Expected output:

```html
<p>This is a <a href="https://example.com" title="Example site">paragraph</a> with a reference-style link.</p>
<p>Here is <a href="https://example.com" title="Example site">another link</a> using the same reference.</p>
<p>And one <a href="https://example.org/foo">more</a> using a different reference.</p>
<p>The references themselves don't appear in the rendered output.</p>
```

With the feature unimplemented (baseline state), this fixture fails — `[text][id]` is rendered as literal bracketed text and the `[id]: url` definition lines appear as paragraphs.

---

## 4. Initial state for Ep 4

Per the convention established in this series: **each episode's `initial/` is the prior episode's "successful completion" state.**

`code/episodes/04-planning-reasoning/initial/` = a copy of Ep 3's successful sandbox output (ASTNode rename applied, all Ep 3 tests passing) **plus the reference_style_links fixture pair.**

The agent's job is to implement the feature so all 44 tests pass.

Setup steps (already done at commit `9a6e4f2`):
1. Start from Ep 3 successful sandbox.
2. Add `tests/fixtures/reference_style_links.md` and `.html`.
3. Confirm baseline: pytest shows 43 pass + 1 fail (only `reference_style_links`).

---

## 5. What changes in `agent.py` vs Ep 3

### Added (~50 LOC)
- `CURRENT_PLAN: list[dict] = []` — module-level plan state.
- `_format_plan(plan)` — render plan as a checklist string.
- `@tool write_plan(steps)` — set/replace the plan, with defensive parsing for the model's quirks (string-vs-list, JSON-string).
- `@tool think(thought)` — no-op echo.
- `_system_cached()` — returns `[base_text_block_with_cache_control, plan_block_without_cache_control]` when a plan exists, otherwise just the base.
- `write_plan` and `think` added to `TOOLS` registry.
- Per-iteration counters for `write_plan` and `think` calls (recorded in the final usage summary).

### Changed from Ep 3
- System prompt: NO change. (Tool descriptions carry the framing.)
- Compaction-trigger threshold check: now uses `input_tokens + cache_read + cache_write` instead of just `input_tokens`, because with caching enabled the raw `input_tokens` field is only the uncached delta and would never cross the threshold.

### Temporarily swapped (dev-time only)
- **LLM SDK**: native Anthropic SDK with prompt caching, instead of the locked `openai` package against Chat Completions. See [[feedback-use-openai-sdk]] in memory and the header docstring in `agent.py`. **Will be translated back before the companion code ships.**

### Unchanged from Ep 3
- Sandbox reset, `@tool` decorator, all 5 working tools (bash/read/write/edit/grep), `done` + `TaskComplete`, `compact()` function, `MAX_ITERATIONS` safety cap.

**Total agent.py:** ~330 LOC (Ep 3 was ~280).

---

## 6. The "before" — Ep 3 agent on the Ep 4 task

We ran the Ep 3 agent (`_before.py`, which is the Ep 3 code reset to point at the same `initial/`) on the reference-style links task. **It completed the implementation** but did NOT call `done()` — exited via naive stop with a free-text response.

| Metric | Value |
|---|---|
| Iterations | 27 |
| Compactions fired | 2 |
| `done()` called | ✗ |
| Estimated cost @ Sonnet 4.6 | ~$0.61 |
| Verification | pytest ✓ / source-only ✓ / done() ✗ |

Linear sequence: explore → read fixtures → read parser → write extension → register → run tests → free-text "done."

Log: `tmp/runs/ep04/runG_before_with_caching.log`.

---

## 7. The "after" — Ep 4 agent on the same task

| Metric | Ep 3 baseline | Ep 4 (planning + think) | Δ |
|---|---:|---:|---:|
| Iterations | 27 | 47 | +74% |
| `write_plan` calls | – | 1 (at start, never updated) | – |
| `think` calls | – | 9 (used like a scratchpad) | – |
| Compactions fired | 2 | 2 | – |
| Cumulative output tokens | 11,734 | 14,543 | +24% |
| Cache write tokens | 70,800 | 100,384 | +42% |
| Cache read tokens | 339,073 | 622,449 | +84% |
| **Estimated cost** | **~$0.61** | **~$0.91** | **+49%** |
| `done()` called | ✗ | ✗ | – |
| Verification | pytest ✓ / source-only ✓ / done() ✗ | pytest ✓ / source-only ✓ / done() ✗ | same |

**Empirical observation (recorded as engineering data; the producer brief surfaces this as a design consideration, not a dramatic headline):** planning + think made the agent more expensive on this task — ~50% cost increase, 74% more iterations, same result. The naive intuition "think before acting → fewer wasted steps" doesn't hold for short tasks. Worth knowing when a builder decides whether to add planning to their own agent. See the producer brief at `tmp/video-creation-notes/episode-04.md` for the build-decision framing (legibility / anti-drift / auditability as the trade-off you're choosing).

**Side observations:**
- The agent treats `write_plan` as one-shot decoration, not a living state machine. Calling it just makes a plan visible; it doesn't make the agent maintain one. **A model-behavior data point worth knowing for builders.**
- The agent uses `think` like a scratchpad — roughly 1 in 5 iters has a `think` call before the next action.
- Caching now works correctly (cache_r:cache_w ratio = 6.2× → reads dominate writes). The earlier broken-caching versions of this run (before the plan-injection fix) had inverted ratios and cost more than the uncached baseline. See [[feedback-prompt-cache-prefix-stability]] in memory.

Log: `tmp/runs/ep04/runF_full_caching_working.log`.

---

## 8. What we explicitly did NOT do (carryover for Ep 5)

- **Multi-agent / delegate.** Stays for Ep 5.
- **Sophisticated loop detection.** Reflection was tried and dropped; not worth the false-positive cost on this task.
- **Pre-`done()` reflection check.** Could be added later; not built.
- **Voluntary `update_plan_step(idx, status)` tool.** The agent updates the plan by calling `write_plan` again with the full revised list — simpler API, same expressive power. (In practice, the model didn't revise the plan at all — see §7 side findings.)
- **Anti-drift stress test on 200+ iteration runs.** The architectural value of planning (a persistent intent that survives compaction) lives in that regime. We didn't test there. The producer brief notes this honestly.

---

## 9. What Eps 5–6 inherit

- The Ep 4 sandbox state at task completion is the natural starting point for Ep 5's `initial/` (per the series convention). Ep 5's post-run state then becomes Ep 6's `initial/`.
- The plan-injection mechanism (dynamic state in system, not messages) is the template Ep 5 extends to carry loaded-skill bodies, and the template Ep 6 inherits for per-worker dynamic state.
- The dev-time SDK swap to native Anthropic + caching applies the same way to Ep 5's and Ep 6's `agent.py` (and must be translated back before shipping).
- The `done()`-reliability gap from Ep 4 stays unresolved through Ep 5 (partially self-resolved by clean-completion-signal tasks) and gets the structural answer in Ep 6 — the verifier worker owns the completion signal, and the orchestrator's `done()` fires after the verifier reports a clean pass. See `feedback_done_reliability_overdue.md` in memory.
- The task-choice lesson — feature-add gave us a harder task than bug-fix — guided both Ep 5 (GH alerts feature-add, anchored research skill use) and Ep 6 (three GFM features at once, naturally parallelisable so orchestration's value is *a priori* plausible).
