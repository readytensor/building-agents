# Episode 3: Compaction

**Concept:** what changes when tasks get long. The message history grows every turn, so each call re-sends the whole transcript — slower and more expensive as the run goes on. The fix is rolling-summary **compaction**: once the older middle of the transcript crosses a token threshold, summarize it with a second model call and replace it with one summary message, so a long run stays affordable.

**This episode's additions on top of Ep 2:** rolling-summary **compaction** (in its own `compaction.py`), plus a `MAX_ITERATIONS` safety cap. Completion stays the **natural stop** from Ep 1 — the loop ends when the model emits no tool calls. (There is no `done` tool; rigorous, test-based completion arrives later as Ep 5's verification skill.)

**Code** (structured like Ep 2: the loop and each mechanism in its own file):
- `agent.py`: Ep 2's agent loop + the per-turn compaction check
- `compaction.py` (**this episode's addition**): the rolling-summary compaction — it triggers on the token count of the compactable middle and summarizes it via a second (cheaper) model call
- `tools.py`: carried forward from Ep 2 unchanged
- `initial/`: `md2html` ready for a multi-file refactor (long enough to trigger compaction)
- `sandbox/`: gitignored, recreated on every run

**Run:**

```bash
python agent.py
```

**Full context:**
- `../../README.md`: companion code repo overview
