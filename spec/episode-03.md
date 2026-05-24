# Episode 3 — Context — Spec

What changes between Episode 2 and Episode 3 — both the agent itself (`code/episodes/03-context/agent.py`) and the toy codebase state in `code/episodes/03-context/initial/`.

For the narrative producer brief: see `tmp/video-creation-notes/episode-03.md` (to be written after implementation + recorded runs).

---

## 1. The exercise

### Task given to the agent

A realistic engineer's request to clean up a name in anticipation of future work — paste-and-ask style, following the convention established in Ep 2.

```python
TASK = """I'm about to start adding inline tokens to the parser, and the
generic name `Node` for our AST type is going to get confusing. Can you
rename `Node` to `ASTNode` throughout the codebase? The change is purely
naming — semantics stay identical. All 43 tests should pass after.
"""
```

### Success criterion (the verification procedure — see §6 for full details)

1. `pytest` returns 43 passed / 0 failed.
2. `grep -rn '\bNode\b' md2html/` returns **0 hits** in source files (no stragglers left).
3. `grep -rn '\bASTNode\b' md2html/` returns approximately **the original 58 hits** (rename actually happened and matches the prior reference count).
4. `diff -r initial sandbox` shows changes only in the expected files.

All four checks must pass for the run to count as successful.

---

## 2. The refactor target

`Node` is the AST type. In the baseline codebase it appears **58 times across 5 files** (counts from `code/episodes/01-loop/initial/`):

| File | Occurrences |
|---|---:|
| `md2html/parser.py` | 23 |
| `md2html/renderer.py` | 20 |
| `md2html/extensions/footnotes.py` | 7 |
| `md2html/extensions/tables.py` | 6 |
| `tests/test_parser.py` | 2 |
| **Total** | **58** |

Why this is the right refactor target for Ep 3:

- **Real motivation.** "We're about to add inline tokens; want to disambiguate" is exactly the kind of pre-emptive cleanup engineers actually do.
- **Touches multiple modules.** Across the parser/renderer/extensions/tests boundary — the agent must coordinate.
- **Mechanical-ish but not trivial.** Every reference must be renamed; a missed one breaks tests.
- **Tests verify completion.** All 43 must still pass after.
- **Big enough blast radius to strain context.** File contents from these 5 files legitimately fill the message history.

### What does *not* get renamed

`Node` in **docstrings, comments, and free-text strings** stays as-is (we're not renaming English prose, only Python identifiers). The agent should figure this out from context; the verification grep (§6) uses `\b` word boundaries, which catches the identifier but is permissive about surrounding text — and we accept a small tolerance for comment text matches.

### Initial state for Ep 3

`code/episodes/03-context/initial/` = exact copy of `code/episodes/01-loop/initial/`. No planted bugs, no other modifications. The refactor work is the task; `initial/` doesn't need to be pre-modified.

---

## 3. The two paired additions

### 3a. The done tool

Replaces the naive stop condition from Eps 1–2.

```python
class TaskComplete(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


@tool("Signal that the task is complete. Pass a clear summary of what was done.")
def done(message: str) -> str:
    raise TaskComplete(message)
```

The outer loop catches `TaskComplete` and treats `e.message` as the final answer:

```python
try:
    ...inside the iteration body...
except TaskComplete as e:
    print(f"\n=== TASK COMPLETE ===\n\n{e.message}")
    break
```

Total addition: ~10 LOC including the exception class.

### 3b. Rolling-summary compaction

After each LLM call, check the message list's cumulative input token estimate. If above threshold, call the LLM with a summary prompt to compress older turns, then replace those turns with a single summary message.

**Threshold for the episode: 30,000 input tokens per single LLM call.** This is intentionally low for demo visibility — production would use 70–80% of the model's context window. The episode should flag this explicitly so viewers don't mistake the threshold for a recommendation.

**What gets preserved in compaction:**

- The original system prompt (always).
- The original user task (always — this is the goal the agent must keep tracking).
- The single summary message (replaces all older intermediate turns).
- The most recent **N = 4 turns** (last 2 assistant messages + last 2 tool results, roughly).

**What gets compacted:** all assistant messages, tool results, and intermediate exchanges between the original user task and the most recent N turns.

**Summarizer prompt** (sent to the same model):

```
You're summarizing an in-progress agent transcript so the agent can keep working with less context. Produce a concise structured summary that includes:

1. The user's task.
2. What's been investigated so far (files read, what was found).
3. What's been changed so far (files written, edits applied).
4. What's still to do (uncompleted work).
5. Any errors encountered and how they were handled.

Be terse but specific. The agent will continue work from this summary; don't omit anything that would force re-investigation.
```

The summary message is inserted into the message list with `role="user"` and a clear prefix like:

```
[CONTEXT COMPACTED — earlier transcript summarized below.]

{summary text from the LLM}

[End of summary. Continue with the most recent {N} turns.]
```

Total addition: ~40–50 LOC.

---

## 4. System prompt change

The **only** system prompt change in the entire series. Last sentence updated:

- **Ep 1 / Ep 2:** *"When the task is complete, stop calling tools and produce a clear answer."*
- **Ep 3 onward:** *"When the task is complete, call `done()` with a clear summary of what you did."*

This is worth a brief callout in the episode — we promised the system prompt would be durable, and it has been, and here is its one and only evolution.

---

## 5. The failure demo

The episode's narrative arc requires showing the agent *failing* (or at least: succeeding expensively) on this refactor task WITHOUT compaction, then succeeding cheaply WITH compaction.

### The "before" — run the Ep 2 agent on the Ep 3 task

The Ep 2 agent (no compaction, no done tool) gets pointed at the rename task. The agent will likely:

- Read multiple files in sequence (each one stays in context permanently).
- Accumulate 50–100K input tokens per iteration by the time it's edited 4–5 files.
- *Possibly* succeed but at high token cost.
- *Possibly* lose the thread — forget which files it's already updated, re-read them, undo changes, drift from the original goal.

**Either failure mode (high cost OR loss of thread) makes the same point.** The episode shows real numbers.

### The "after" — run the Ep 3 agent

The Ep 3 agent with compaction (threshold 30K) and done tool. Predicted:

- Compaction fires 1–3 times during the run.
- Cumulative input tokens stay in the 100–150K range despite touching the same 5 files.
- Same 4-check verification passes.
- Often finishes in fewer iterations because the agent isn't paying token tax on stale context.

### Predicted headline number

| | Ep 2 agent on refactor task | Ep 3 agent on refactor task |
|---|---|---|
| Cumulative input tokens | 400K–600K | 100K–150K |
| Cost @ Sonnet 4.6 | ~$1.50 | ~$0.40 |
| Same correctness? | Yes (or close) | Yes |

**3–5× cost difference on the same task. Same correctness. That's the lesson.**

The exact numbers will be measured at recording time and locked into the producer brief.

---

## 6. Verification procedure (non-negotiable)

After each recorded agent run, run this four-step verification. **All four must pass** for the run to count as a successful demo.

```bash
# 1. Tests pass
cd sandbox && python -m pytest -q
# Expected: "43 passed in X.XXs"

# 2. No stray Node references remain in source (CASE-SENSITIVE — matters!)
grep -rn '\bNode\b' md2html/ | wc -l               # POSIX grep is case-sensitive
# PowerShell equivalent:
# (Select-String -Path 'md2html\*.py','md2html\extensions\*.py' -Pattern '\bNode\b' -CaseSensitive).Count
# Expected: 0
# Why -CaseSensitive matters: lowercase "node" appears in ~90 places as variable
# names and comments. A case-insensitive grep gives the wrong answer.

# 3. The rename actually happened across all expected files (also CASE-SENSITIVE)
grep -rn '\bASTNode\b' md2html/ | wc -l
# Expected: ~56 (was 58 in baseline; small drop possible from comment dedup)

# 4. Manual diff (eyeball check)
cd .. && diff -r initial sandbox
# Expected: only renaming changes in: parser.py, renderer.py,
#   extensions/footnotes.py, extensions/tables.py, tests/test_parser.py
```

If a run fails ANY of these, we either:

- Re-run (variance might land it correctly next time), or
- Note the failure in the producer brief as a teaching moment about agent reliability ("Run 2 left 3 stray Node references — see §X for what that tells us"), or
- Iterate on the system prompt or compaction parameters if failures are systematic.

What we **don't** do:

- Hand-fix the agent's output before claiming success.
- Lower the bar to count partial renames as "good enough."
- Pre-write tests that artificially require `ASTNode` (that'd encode the answer; not a real-engineer check).

The verification commands above are the entire bar. They're what a real engineer would run reviewing this PR.

---

## 7. Per-run verification log (filled in at recording time)

For each of the 3 recorded runs (A, B, C), capture:

```
Run A
  iterations: __
  tool calls: __
  cumulative input tokens: __
  cumulative output tokens: __
  pytest result: __ passed / __ failed
  grep '\bNode\b' count: __        (must be 0)
  grep '\bASTNode\b' count: __     (must be ~58)
  diff scope: files modified = __  (must be the expected 5)
  PASS / FAIL: __

Run B
  ...

Run C
  ...
```

This log goes in the producer brief once recorded.

---

## 8. Expected agent trajectory

Not deterministic, but a plausible path:

1. `bash("pytest -q")` — confirm baseline (43 pass).
2. `grep("Node", "md2html")` or read across files — find where `Node` is defined and referenced.
3. `read("md2html/parser.py")` — see the class definition + usages.
4. `read("md2html/renderer.py")` — see visitor methods that take `Node`.
5. `read("md2html/extensions/...")` — see extension hooks.
6. Series of `edit(...)` calls or larger `write(...)` calls — apply the rename across each file.
7. Periodic `bash("pytest -q")` — verify after each module or at the end.
8. `done("Renamed Node to ASTNode across 5 files...")` — explicit completion.

**Compaction should fire 1–3 times** during this run if the threshold is calibrated correctly.

Expected ranges:

- Tool calls: 15–30 (more than Ep 2 because more files to touch).
- Iterations: similar range.
- Cumulative input: 100–150K with compaction.

---

## 9. What changes in `agent.py`

### Diff sketch from Ep 2

**Added:**

- `TaskComplete` exception class (~3 lines).
- `done(message: str)` tool, decorated with `@tool` (~3 lines).
- `compact(messages, llm)` function that calls the LLM with the summarizer prompt and replaces history (~25–35 lines including the prompt string).
- A `try/except TaskComplete` around the loop body (~3 lines).
- After each LLM call: check `u.prompt_tokens > COMPACTION_THRESHOLD`, call compaction (~3–5 lines).
- `done` added to `TOOLS` list.

**Modified:**

- `SYSTEM` prompt's last sentence (one line change).

**Unchanged from Ep 2:**

- `@tool` decorator definition.
- `bash`, `read`, `write`, `edit`, `grep` tool definitions and bodies.
- Tool registry pattern.
- Token instrumentation print lines.
- Sandbox reset, LLM client setup.

### LOC growth

| | LOC (approx) |
|---|---|
| Ep 2 `agent.py` | ~170 |
| Ep 3 `agent.py` | ~220 |

Most of the growth (~50 LOC) is the compaction function + its prompt.

---

## 10. What changes in `code/episodes/03-context/initial/`

**Nothing.** Exact copy of `code/episodes/01-loop/initial/`. The refactor is the task, not a planted bug or modified state.

Implementation order will be: `python -c "import shutil; shutil.copytree('../01-loop/initial', '.', dirs_exist_ok=True, ignore=...)"` and that's it.

---

## 11. Out of scope for this episode

- **Planning and in-the-moment reasoning tools.** Both arrive in Ep 4. (Reflection was originally going to be Ep 4's other addition; cut during implementation after trials produced false positives without catching real spirals.)
- **Ephemeral messages.** We picked compaction over ephemeral earlier; sticking with that.
- **Multi-agent / delegation.** Stays out until Ep 5.
- **Pydantic-model tool parameters.** Stays out of the series.
- **Production-grade compaction.** What we implement is the minimum viable mechanism — same model, simple prompt, hard threshold. Production agents add: separate cheaper model for summarization, prompt caching, configurable retention windows, etc. Mention these exist; don't build them.

---

## 12. Implementation order (when we get there)

1. Copy `code/episodes/01-loop/initial/` → `code/episodes/03-context/initial/`.
2. Verify baseline pytest passes (43/43) in the fresh initial state.
3. Write `code/episodes/03-context/agent.py`:
   - Start from Ep 2's `agent.py`.
   - Add `TaskComplete` + `done` tool.
   - Add `compact()` function and the threshold check in the loop.
   - Update the system prompt's last sentence.
   - Catch `TaskComplete` in the loop, treat as successful exit.
4. **First — record the "before" demo:** run the Ep 2 agent against the Ep 3 task. Capture trajectory + token totals + verification results. This becomes the failure-mode evidence in the producer brief.
5. **Then — record the "after" demos:** run the Ep 3 agent 3 times against the same task. Apply the §6 verification to each. Log per §7.
6. If any of the 3 runs fails verification, decide: re-run (variance), tweak compaction params, or flag as teaching moment.
7. Write the producer brief (`tmp/video-creation-notes/episode-03.md`).

---

## 13. Open questions to settle during implementation

These are minor — flag here so we don't forget when building:

- **Retention window N.** Spec says "last 4 turns" preserved at compaction. Might need to tune to 2-6 based on demo runs.
- **Summary message role.** Spec says `role="user"` with a clear `[CONTEXT COMPACTED]` prefix. Alternative: insert as a fake assistant message. User-role is conventionally what compaction tools use; let's start there.
- **Threshold knob — sticky vs. recalculated.** After compaction, the next iteration's input is reset low. The threshold continues to trigger on cumulative input per single call. Stick with that.
- **Compaction telemetry.** Should the agent print `[COMPACTION FIRED — N tokens → M tokens]` when it happens? Yes — visible in the demo, matches the ambient instrumentation style.
