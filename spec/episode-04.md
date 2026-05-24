# Episode 4 — Planning & Reflection — Spec

What changes between Episode 3 and Episode 4 — both the agent itself (`code/episodes/04-planning-reflection/agent.py`) and the toy codebase state in `code/episodes/04-planning-reflection/initial/`.

For the narrative producer brief: see `tmp/video-creation-notes/episode-04.md` (to be written after implementation + recorded runs).

---

## 1. The exercise

### Task given to the agent

A realistic engineer's bug report — paste-and-ask, same convention as Eps 2 and 3:

```python
TASK = """I'm seeing this when I run pytest in this repo:

FAILED tests/test_renderer.py::test_fixture_pair[tables_in_lists]
AssertionError: rendered HTML doesn't match expected.
See tests/fixtures/tables_in_lists.md / tables_in_lists.html for the input
and what the output should be.

Can you figure out what's wrong and fix it?"""
```

### Success criterion — 4-step verification (same shape as Ep 3 §6)

1. `pytest` returns N passed / 0 failed (N = baseline count after we add the new fixture).
2. The fix is in source code, not in the fixture (the agent didn't "fix" the test by altering expected output).
3. `diff -r initial sandbox` shows changes only in the expected file(s) — the agent didn't refactor unrelated code on the way.
4. The agent called `done()` after verifying.

All four must pass for a recorded run to count as successful.

---

## 2. The planted defect — "tables inside nested list items render wrong"

A test fixture where a Markdown table appears inside a list item. The expected HTML has the table as an `<table>...</table>` element. The bugged output produces literal pipe characters (the table tokenizer doesn't fire inside list-item content).

### Why this bug

- **Genuinely ambiguous root-cause location.** Plausible candidates:
  - **Lexer** — table tokenizer not invoked when scanning list-item body lines.
  - **Parser** — list-item content not re-tokenized through extension hooks.
  - **Tables extension** (`extensions/tables.py`) — `tokenize_block` hook gated to top-level blocks only.
- **Failure is visible** — the diff between expected `<table>...</table>` and actual `<p>| col1 | col2 |</p>` is unmissable.
- **Investigation is non-trivial** — the agent has to read the extension protocol in `extensions/__init__.py`, understand how `tokenize_block` is dispatched, trace where it's called from in the lexer/parser.
- **Forces multi-hypothesis thinking** — the agent could plausibly start fixing the wrong module first, find that "fix" doesn't work, need to back up and reconsider. **That's exactly what reflection is for.**

### Where the bug actually lives (the canonical plant point)

The bug is in **`md2html/extensions/tables.py`** — specifically, the `tokenize_block` hook is gated by a check that only fires at top-level block scanning, not when called from inside list-item content re-parsing.

But the agent shouldn't be told this. The agent must investigate and narrow it down.

### Open item to confirm during implementation

The current `md2html` codebase may not actually support tables inside list items as a working feature — meaning we may need to **first add baseline support, then plant the bug**. To be confirmed when we build Ep 4's `initial/`. If the codebase doesn't naturally support tables-in-lists, two paths:

- **Add the feature, then plant the regression** — more setup work, cleanest narrative ("this used to work, now it's broken").
- **Pick a different ambiguous bug** — e.g., "code block inside a list item loses its language class" or "footnote definition inside a blockquote renders wrong." Same pedagogical shape, possibly simpler baseline.

To be settled at implementation time.

---

## 3. New test fixture

A new pair of files under `tests/fixtures/`:

### `tests/fixtures/tables_in_lists.md`

```markdown
Here's a list with a table inside one of the items:

- First item, regular text.
- Second item containing a table:

  | col1 | col2 |
  |------|------|
  | a    | b    |
  | c    | d    |

- Third item, back to regular text.
```

### `tests/fixtures/tables_in_lists.html`

Expected output (table renders inside the list item):

```html
<p>Here's a list with a table inside one of the items:</p>
<ul>
<li>First item, regular text.</li>
<li>Second item containing a table:
<table>
<thead><tr><th>col1</th><th>col2</th></tr></thead>
<tbody>
<tr><td>a</td><td>b</td></tr>
<tr><td>c</td><td>d</td></tr>
</tbody>
</table>
</li>
<li>Third item, back to regular text.</li>
</ul>
```

(Exact HTML formatting will be finalized when we verify the baseline's output style.)

With the bug present, **only this test fails**. All previously-passing tests still pass.

---

## 4. The two paired additions

### 4a. The planning tool (`write_plan`)

A Claude Code-style TodoWrite-equivalent. Tool-based, with persistent context injection.

```python
class PlanStep(TypedDict):
    content: str          # description of the step
    status: str           # "pending" | "in_progress" | "completed"


# Module-level state — the canonical plan, mutated by the tool.
CURRENT_PLAN: list[PlanStep] = []


@tool(
    "Set or update the working plan. Pass the FULL current state of the plan as "
    "a list of steps, each with content and status. Use this to enumerate "
    "subtasks, track progress, and revise the plan when you learn something new."
)
def write_plan(steps: list[dict]) -> str:
    CURRENT_PLAN.clear()
    CURRENT_PLAN.extend(steps)
    return _format_plan(CURRENT_PLAN)
```

The plan is **injected into context on every LLM call** as a `role="user"` message inserted just before the call (and removed afterward to avoid polluting message history):

```python
def _inject_plan_into_messages(messages: list[dict]) -> list[dict]:
    if not CURRENT_PLAN:
        return messages
    plan_msg = {
        "role": "user",
        "content": f"[CURRENT PLAN]\n{_format_plan(CURRENT_PLAN)}\n[end plan]",
    }
    # Insert just before the most recent user/assistant exchange so it stays fresh
    return messages + [plan_msg]
```

**Why persistent injection (and not just adding to messages)**: compaction would otherwise eventually summarize the plan away. By injecting from agent state each call, the plan is always current and complete, regardless of compaction.

**~30 LOC** of new code total: the tool, the injection helper, the state variable.

### 4b. Reflection — loop-based, two triggers

Reflection is NOT a tool. The agent loop detects trigger conditions and injects a user message that forces the model to reflect on the next iteration.

**Trigger 1: Tool returned an error.**

```python
def _looks_like_error(tool_result: str) -> bool:
    return tool_result.startswith("Error executing") or tool_result.startswith("Error:")
```

When detected, after appending the tool result, inject:

```
[REFLECT] That tool call failed. Briefly reflect on what went wrong, then try a different approach.
```

**Trigger 2: Loop detected — same tool, same args, in the last N=5 iterations.**

```python
def _is_likely_loop(call_signature, recent_signatures, window=5):
    if _is_known_verification_pattern(call_signature):
        return False  # bash("pytest") and similar — don't trigger
    return call_signature in recent_signatures[-window:]
```

When detected, inject:

```
[REFLECT] You just called this with the same arguments earlier. Step back — are you
stuck in a loop? Reflect on whether the current approach is working, then try
something different.
```

**Known false-positive case acknowledged.** When the agent is legitimately running the same command repeatedly because something happens between calls (e.g., a migration script that tracks its own state), the heuristic will fire. The cost is one extra LLM call where the agent says "I'm intentionally iterating, continuing." Acceptable.

**Implementation: ~25 LOC** — the helper functions, a `recent_signatures` deque, the injection logic in the loop.

### Combined LOC for Ep 4 additions

- Planning: ~30 LOC
- Reflection: ~25 LOC
- **Total: ~55 LOC** added to Ep 3's agent.

Ep 3 was ~280 LOC. Ep 4 will be **~335 LOC**.

---

## 5. Initial state for Ep 4 — inheriting Ep 3's output

Per the convention established in this series: **each episode's `initial/` is the prior episode's "successful completion" state.**

`code/episodes/04-planning-reflection/initial/` = a copy of `code/episodes/03-context/_sandbox_from_runA/` (the literal output of Ep 3 Run A — Node renamed to ASTNode across 5 files, 43 tests pass) **plus the new `tables_in_lists` fixture pair and the planted bug.**

### Concretely, the setup steps when we build it

1. Run the Ep 3 agent against the Ep 3 task one final time to produce a clean "Ep 3 done" sandbox (or use the existing Run A output if still on disk).
2. Copy that sandbox → `code/episodes/04-planning-reflection/initial/`.
3. Verify baseline: `pytest` shows 43/43 pass, `grep '\bNode\b' md2html/` returns 0.
4. Plant the bug in `extensions/tables.py` per §2.
5. Add `tables_in_lists.md` / `.html` fixture pair.
6. Re-verify: 43 pass + 1 fail (only `tables_in_lists`).

The agent's job is then exactly the same shape as Ep 3 (a failing test, find and fix) but **with an ambiguous root cause** that exercises the new planning + reflection mechanisms.

---

## 6. The failure demo — Ep 3 agent on Ep 4 task

The episode's narrative arc requires showing the Ep 3 agent **struggling** on this task — likely succeeding eventually, but visibly inefficient, with signs of the failure modes (charging in wrong, having to back up).

**Expected Ep 3-agent behavior on the ambiguous bug:**

- Reads the fixture pair, sees expected vs actual.
- Charges into ONE module first (often the most "obvious" candidate, which may not be where the bug is).
- Tries a fix, runs pytest, sees it still fails.
- Tries another fix in the same module, still fails.
- Eventually backs up, considers another module.
- May or may not succeed within MAX_ITERATIONS (150).

If the Ep 3 agent succeeds, it'll take **many more iterations than necessary** because it lacks structured hypothesis-tracking. If it fails or hallucinates completion, the failure case lands even harder.

**The "after" — Ep 4 agent on same task:**

- First move: `write_plan(["Investigate lexer for table handling in list contexts", "Investigate parser for list-item content re-parsing", "Investigate tables extension's gating", "Apply fix to identified module", "Verify with pytest"])`.
- Works through the plan systematically. Marks each step in_progress, then completed.
- When a fix attempt fails, reflection triggers (tool error or repeated bash call). Agent says "this hypothesis was wrong, the bug isn't in module X — let me update my plan." Calls `write_plan` again with revised steps.
- Eventually localizes to the correct module, applies fix, verifies, calls done.

**Expected contrast for the episode**: Ep 3 agent grinds through this in ~40+ iterations with visible thrashing; Ep 4 agent does it in ~25-30 with a visible plan that updates as understanding grows.

---

## 7. What changes in `agent.py`

### Diff sketch from Ep 3

**Added:**
- `CURRENT_PLAN: list[PlanStep] = []` module-level state.
- `_format_plan(plan)` helper for rendering plan into context.
- `@tool write_plan(steps)` function.
- `_inject_plan_into_messages(messages)` helper.
- `_recent_signatures: deque` for loop detection.
- `_looks_like_error(result)` helper.
- `_is_likely_loop(sig, recent)` helper.
- `_is_known_verification_pattern(sig)` allowlist function.
- Inside the loop:
  - After each tool result, check error → inject reflection prompt if needed.
  - After each tool result, check loop signature → inject reflection prompt if needed.
  - Before each LLM call, inject the current plan via `_inject_plan_into_messages`.
- `write_plan` added to `TOOLS` registry.

**Unchanged from Ep 3:**
- Sandbox reset, LLM client, `@tool` decorator.
- All five working tools + `done`.
- `TaskComplete` exception handling.
- `compact()` function.
- System prompt (NO change — the plan tool's description tells the agent what to do).

### System prompt: no change

The agent discovers it should use `write_plan` from the tool's description. No system-prompt sentence to add or modify. This stays consistent with our principle that the system prompt evolves at most once across the series (Ep 3 was that change).

---

## 8. What changes in `initial/`

Per §5:

1. Start from Ep 3 Run A's sandbox output (Node → ASTNode rename applied, 43 tests pass).
2. Add `tests/fixtures/tables_in_lists.md` and `tests/fixtures/tables_in_lists.html`.
3. Plant the bug in `md2html/extensions/tables.py` (gating issue).
4. Possibly: add baseline support for tables-in-lists first if not already present (see §2 "open item").

Nothing else changes.

---

## 9. Verification procedure

Same 4-step shape as Ep 3 §6, adapted:

```bash
# 1. Tests pass
cd sandbox && python -m pytest -q
# Expected: "44 passed in X.XXs"  (43 from Ep 3 + 1 new = 44)

# 2. The fix is in source, not the fixture
diff initial/tests/fixtures/tables_in_lists.html sandbox/tests/fixtures/tables_in_lists.html
# Expected: empty (fixture unchanged — agent didn't "fix" the test)

# 3. Diff scope — agent only changed expected files
diff -r initial sandbox
# Expected: changes ONLY in md2html/extensions/tables.py (or wherever the bug
# was localized). Bonus: PLAN-related state isn't in sandbox (plan is in agent
# memory, not files).

# 4. done() was called
grep "TASK COMPLETE" run.log
# Expected: present
```

Plus instrumentation we want to capture for the producer brief:

- Did `write_plan` actually get used? (count of `> write_plan(...)` in trajectory)
- How many times was the plan revised? (count of subsequent `write_plan` calls beyond the first)
- How many reflections fired? (count of `[REFLECT]` injections)
- For each reflection: tool-error or loop-detection?
- Iteration count vs Ep 3 agent on same task (the headline contrast)

---

## 10. Out of scope for this episode

- **Multi-agent / delegation.** Stays for Ep 5.
- **Voluntary `reflect(thought)` tool.** Reflection is loop-imposed, not model-volunteered.
- **Sophisticated loop detection** (state hashing, progress markers, ML classifier). Simple `(name, args)` exact-match heuristic with verification allowlist is enough. Pedagogical framing on screen: "this is the minimum viable detector; production systems do more."
- **Pre-`done()` reflection check** (Option C from the design discussion). Could be added later if Runs A/B/C show "hallucinated success" recurring; not in v1.
- **Voluntary `update_plan_step(idx, status)` tool.** The agent updates the plan by calling `write_plan` again with the full revised list — simpler API, same expressive power.

---

## 11. Implementation order (when we get there)

1. **Verify or build baseline support for tables-in-lists.** Either confirm md2html handles this natively today, OR add the support code first. Either way, we need a "working baseline" state where the new fixture WOULD pass before we plant the bug.
2. **Build Ep 4's `initial/`** per §8: copy from Ep 3 Run A's sandbox, add fixture pair, plant bug.
3. **Verify baseline**: pytest shows 43 + 1 = 44 tests collected, only `tables_in_lists` fails.
4. **Write `code/episodes/04-planning-reflection/agent.py`** per §7.
5. **First — record the "before" demo**: run the Ep 3 agent against the Ep 4 task. Capture trajectory, iteration count, success/failure.
6. **Then — record the "after" demos**: run the Ep 4 agent against the same task 3 times. Capture each per §9 instrumentation.
7. **If any run fails verification, decide**: re-run (variance), tune trigger conditions, or note as a teaching moment.
8. **Write the producer brief** (`tmp/video-creation-notes/episode-04.md`).

---

## 12. Open items to confirm during implementation

- **Whether the baseline supports tables-in-lists.** §2's open item. Could change the bug choice if too much setup work.
- **Final loop-detection window N**. Spec says 5; might tune based on Ep 4 runs.
- **Verification allowlist** for loop detection. Spec says `pytest`, `make test`, `go test` — may need to expand based on what verification commands the agent actually uses.
- **Whether `write_plan` should require the plan to be non-empty.** Currently allows empty plans (calling with `[]`); maybe error if the agent tries to clear the plan partway through a task?
- **Where the `[CURRENT PLAN]` injection appears in the message list.** Spec says "appended just before the LLM call" — could also be at the start of the user task or as a system reminder. To be settled when we see how the model responds.
