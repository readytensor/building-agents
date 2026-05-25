# Episode 6 — Orchestration — Spec

What changes between Episode 5 and Episode 6 — both the agent itself (`code/episodes/06-orchestration/agent.py`) and the surrounding scaffold (a new `.agents/` directory in `initial/`).

For the narrative producer brief and the empirical comparison: see `tmp/video-creation-notes/episode-06.md` (to be written after recording).

For the broader library of skills this series is building, and how Ep 6's worker types reuse them: see `tmp/skills-library/README.md`.

> **Spec authoring note:** like Ep 5, this spec is written *before* implementation, close enough to the intended code that minimal post-hoc reconciliation should be needed. Sections 7 and 8 (before/after metrics, empirical observations) will be filled in after recording.

---

## 1. The exercise

### Task given to the agent

A realistic engineer's request, same convention as Eps 2–5 (fixtures pre-exist; the agent's job is to make them pass):

```python
TASK = """I want to round out our GFM support with three more features:

  1. Strikethrough: ~~text~~ → <del>text</del>
  2. Task lists: list items starting with `- [ ]` or `- [x]` render
     with a disabled <input type="checkbox"> prepended (checked for [x]).
  3. Autolinks: <https://example.com> → <a href="https://example.com">https://example.com</a>

Add each as a new extension under md2html/extensions/ and register
each in md2html/extensions/__init__.py. There are test fixture pairs
at tests/fixtures/strikethrough.{md,html}, task_lists.{md,html}, and
autolinks.{md,html} — all three currently fail because the features
aren't implemented.

Make sure all existing tests still pass. Keep diffs minimal."""
```

### Why this task

- **Forces orchestration's value-add to be a priori plausible.** Three independent features = a natural decomposition into parallel workers. The mechanism's "why" (parallel execution) is visible in the trajectory — the orchestrator should batch three `delegate` calls in one assistant turn.
- **Each feature has a fixture pair as ground truth.** Verification is binary (fixture renders correctly or it doesn't), not qualitative. The verifier worker's job is mechanical: run pytest, confirm each fixture passes, confirm diff scope clean.
- **No new spec material needed from outside training.** Strikethrough, task lists, and autolinks are GFM-standard; the model knows the shapes. (Contrast with Ep 5, which forced `research` by picking a feature with version-sensitive class names.)
- **Continuity with the series.** Same "engineer paste-and-asks" convention. md2html stays the surface. Sandbox starting state = Ep 5's post-run sandbox (GH alerts already implemented, `.skills/` present).

---

## 2. Sandbox starting state (`initial/`)

Ep 5's post-run sandbox state verbatim, **plus** three new artifacts:

- `tests/fixtures/strikethrough.{md,html}` — fixture pair
- `tests/fixtures/task_lists.{md,html}` — fixture pair
- `tests/fixtures/autolinks.{md,html}` — fixture pair
- `.agents/implementer.md` — worker config (see §4)
- `.agents/verifier.md` — worker config (see §4)

Baseline `pytest -q`: **45 passed + 3 failed** (Ep 5's 45 + 3 new fixtures that fail because features aren't implemented).

`.skills/` carries forward unchanged from Ep 5 (`research`, `verification`) — workers can load skills the same way Ep 5 agents do.

---

## 3. Success criteria — 6-step verification

```bash
# 1. All tests pass (45 baseline + 3 new = 48)
pytest -q                                                  # → "48 passed"

# 2. Each new extension exists as its own file
ls md2html/extensions/strikethrough.py
ls md2html/extensions/task_lists.py
ls md2html/extensions/autolinks.py                         # all → exist

# 3. Fixtures unmodified (verifier didn't cheat by editing them)
diff -r initial/tests/fixtures sandbox/tests/fixtures      # → no diff

# 4. Diff scope — only md2html/extensions/ + __init__.py
diff -r initial sandbox | grep -vE "fixtures|extensions|__init__"   # → empty

# 5. Orchestrator called done()
grep "=== TASK COMPLETE ===" <run.log>                     # → match

# 6. Orchestrator delegated (instrumentation visibility)
grep -c "^\[orch\] > delegate(" <run.log>                  # → ≥ 4
                                                           # (3 implementers + ≥1 verifier)
```

Criterion #6 is structurally guaranteed (orchestrator has no edit tools — see §5), but listing it makes the teaching point explicit in the verification.

---

## 4. Worker types — `.agents/` directory

Mirrors Claude Code's `.claude/agents/` and the Claude Agent SDK's `AgentDefinition`. Each worker type is a markdown file with YAML frontmatter + a system-prompt body.

### `.agents/implementer.md`

```yaml
---
name: implementer
description: |
  Implement a focused, well-scoped feature in the codebase. Reads source,
  writes new modules, verifies its own work before reporting back. Workers
  of this type are the ones that actually edit code.
tools: [bash, read, write, edit, grep, list_skills, load_skill, write_plan, think, done]
skills: [verification]
---
You are an implementer. Your job is to implement the requested feature.

Discipline:
- Read the relevant files to understand the codebase shape before writing.
- Write your code as a focused, minimal change. Don't refactor unrelated code.
- Run the relevant tests yourself before calling done().
- Your done() summary should describe what you implemented, where, and any
  notable decisions — the orchestrator will pass that summary forward to
  downstream workers.
```

### `.agents/verifier.md`

```yaml
---
name: verifier
description: |
  Confirm that other workers' implementations meet stated criteria. Read-only
  on the codebase (no write/edit tools); runs tests, lint, grep, diff;
  reports per-criterion pass/fail.
tools: [bash, read, grep, list_skills, load_skill, write_plan, think, done]
skills: [verification]
---
You are a verifier. For each criterion you were given, run the verification
command (pytest, lint, grep, diff) and report a structured per-criterion
pass/fail in your done() summary.

Discipline:
- Do NOT modify files. (Your tools don't allow it, but more importantly:
  your role is to verify, not fix.)
- If anything fails, report the failure clearly so the orchestrator can
  decide what to do next (re-dispatch an implementer, abandon, etc.).
- Cite evidence: include the pytest output, the lint output, the grep
  output — don't claim "tests pass" without showing them.
```

### Why two worker types and not three (no `researcher`)

Ep 5 discipline carried forward: ship only what the demo uses. The chosen task has no information gap that requires `research` — strikethrough, task lists, autolinks are GFM-standard, the model knows them. Shipping a `researcher` worker that the orchestrator never invokes would be noise.

The `research` skill remains in `.skills/` (carried over from Ep 5), so a hypothetical Ep 6 task that needed it could just add a `researcher.md` worker config that pre-loads it. The pattern is open-ended.

### Orchestrator's role

The orchestrator is **also** an agent definition, but a special one: it doesn't live in `.agents/`. It's loaded directly from the agent.py module (see §5). Its tools: `list_skills, write_plan, think, delegate, done`. **No `read`/`write`/`edit`/`bash`/`grep`** — every codebase mutation must go through a worker. Role enforcement by toolset, not by exhortation.

---

## 5. The mechanism

### `delegate` tool

```python
@tool("Spawn a worker agent to do `task`. agent_type ∈ {'implementer', 'verifier'}. "
      "Returns the worker's done() summary. Multiple delegate calls in one "
      "assistant turn run CONCURRENTLY via ThreadPoolExecutor.")
def delegate(task: str, agent_type: str) -> str:
    return run_agent(task, agent_type)
```

### `run_agent` — the recursive structure

The whole agent loop is one function, used recursively:

```python
def run_agent(task: str, agent_type: str) -> str:
    """The whole agent loop. The orchestrator IS a worker — `run_agent`
    is called at the top level for the orchestrator, and recursively
    from delegate() for each worker."""
    cfg = AGENT_CONFIGS[agent_type]            # tools, skills, prompt addendum
    tools_by_name = {t: TOOL_FUNCTIONS[t] for t in cfg.tools}
    loaded_skills = {s: _load_skill_body(s) for s in cfg.skills}
    plan: list[dict] = []
    messages = [{"role": "user", "content": task}]
    # ... Ep 5's loop body, reading from these locals not module globals ...
    # ... returns done_summary when worker calls done() ...
```

Key insight: there's no separate "manager loop." The orchestrator and workers all run through `run_agent`. The differences between orchestrator and workers are entirely captured by their config (`AgentConfig`).

### `AgentConfig` registry

```python
@dataclass(frozen=True)
class AgentConfig:
    name: str
    description: str
    tools: list[str]
    skills: list[str]
    prompt: str             # system-prompt addendum (frontmatter body)

AGENT_CONFIGS: dict[str, AgentConfig] = _load_agent_configs(SANDBOX / ".agents")
# Plus a hardcoded orchestrator entry:
AGENT_CONFIGS["orchestrator"] = AgentConfig(
    name="orchestrator",
    description="(top-level orchestrator; not exposed via delegate)",
    tools=["list_skills", "write_plan", "think", "delegate", "done"],
    skills=[],
    prompt="You are an orchestrator. Decompose the task into focused workers...",
)
```

The `.agents/<name>.md` parser is the same idea as Ep 5's `.skills/<name>/SKILL.md` parser — YAML frontmatter + body. Reuses the same `_parse_yaml_frontmatter` helper.

### Parallel dispatch

When the parent's assistant turn includes multiple `delegate` tool_use blocks, dispatch them concurrently. ~15 LOC:

```python
delegate_uses = [b for b in tool_uses if b.name == "delegate"]
other_uses = [b for b in tool_uses if b.name != "delegate"]

# Dispatch concurrently if more than one delegate this turn.
if len(delegate_uses) > 1:
    with ThreadPoolExecutor(max_workers=len(delegate_uses)) as pool:
        futures = {
            pool.submit(run_agent, b.input["task"], b.input["agent_type"]): b
            for b in delegate_uses
        }
        for fut in as_completed(futures):
            b = futures[fut]
            tool_results.append({
                "type": "tool_result", "tool_use_id": b.id,
                "content": fut.result(),
            })
elif len(delegate_uses) == 1:
    b = delegate_uses[0]
    tool_results.append({
        "type": "tool_result", "tool_use_id": b.id,
        "content": run_agent(b.input["task"], b.input["agent_type"]),
    })

# Then dispatch other_uses sequentially (existing path).
```

This matches Claude Code / Agent SDK's pattern: multiple Agent tool_uses in one turn → concurrent.

### Logging hygiene

Workers running concurrently both print to stdout. Without a prefix, the transcript is illegible. A small `_with_prefix(label, fn)` wrapper prepends `[orch]`, `[w1-implementer]`, `[w2-implementer]`, etc. to every print. ~10 LOC. Worker labels are assigned in the order delegate calls fire (`w1`, `w2`, `w3`...).

### What workers see

- `messages = [{"role": "user", "content": task}]` — just the task string, no inheritance
- System prompt = base SYSTEM + agent_type's prompt addendum
- Tools = the agent_type's tools allowlist (resolved against `TOOL_FUNCTIONS`)
- Pre-loaded skills = the agent_type's skills (loaded via the existing `load_skill` machinery before the first turn)
- Workers can still call `list_skills`/`load_skill` mid-run to load additional skills

Workers DO NOT see: parent's messages, parent's plan, parent's loaded skills, other workers' outputs.

### Recursive delegation

Workers don't get `delegate` in their toolset. Depth capped at 1. Matches Claude Code / Agent SDK. Keeps the mental model two-level for teaching.

### Iteration cap

`MAX_WORKER_ITER` (env-overridable, default 40). If hit, `delegate` returns:

```
"Worker '<agent_type>' exceeded iteration cap (40 iters) without calling done().
Last assistant text: <preview>"
```

The orchestrator then sees this as a normal tool_result and decides what to do (re-dispatch, abandon, etc.).

### Shared sandbox

All workers share the same `sandbox/` cwd. Disjoint-file work (different extensions) is safe; if two workers ever touched the same file, last-writer-wins. The orchestrator's job is to decompose so this doesn't happen. We accept this constraint over the complexity of per-worker sandboxes.

---

## 6. Code-shape delta vs. Ep 5 (~400 LOC)

| Component | Δ LOC | Note |
|---|---|---|
| `run_agent` (extract Ep 5's loop into a function) | +0 net | Same code, function-wrapped. Module globals → function locals. |
| `AgentConfig` dataclass + `.agents/` parser | +30 | Mirrors Ep 5's skill parser. |
| `delegate` tool | +5 | Calls `run_agent`. |
| `ThreadPoolExecutor` parallel dispatcher | +20 | In the tool-call loop. |
| Worker-id logging prefix wrapper | +15 | `with _label("w1-implementer"): print(...)` pattern. |
| Orchestrator's `AgentConfig` hard-coded | +10 | Plus a base SYSTEM constant per agent_type. |
| `MAX_WORKER_ITER` + iter-cap return path | +5 | Worker hitting cap returns error to parent. |
| **Total Ep 6** | **~485 LOC** | ~85 LOC delta on Ep 5. |

---

## 7. Empirical observations

Two recorded runs. **v2 is the canonical run** (used for the producer brief and the locked record). v1 surfaced an antipattern that motivated a prompt-strengthening pass.

### 7a. v2 — canonical run

System prompt: strong-wording orchestrator (the `ORCHESTRATOR_SYSTEM` constant shipped in `agent.py`; mandates parallel batching of ≥2 independent subtasks, explicitly names the antipattern of recon-then-dispatch).

| Metric | Value |
|---|---|
| Workers spawned | 5 (1 orchestrator + 3 parallel implementers + 1 verifier) |
| Orchestrator iters | 7 |
| Parallel batches fired | 1 (of 3 implementers, at orch iter 4) |
| Per-worker iters (implementers) | 26 / 28 / 29 |
| Verifier iters | 5 |
| `done()` calls | 5/5 — every agent terminated cleanly |
| `write_plan` calls (orchestrator) | 1 (orch iter 3) |
| Skills loaded | `verification` (preloaded into each worker via config) |
| pytest result | 48/48 ✓ |
| Cache write / read (aggregate) | 116K / 1.84M tokens |
| Output tokens (aggregate) | 19.5K |
| Estimated cost @ Sonnet 4.6 | ~$1.28 |
| Wall time | ~4 min |

**Trajectory shape:**
```
[orch]  iter 1: list_skills()
[orch]  iter 2: think (decompose)
[orch]  iter 3: write_plan (3 implementations + 1 verify)
[orch]  iter 4: >>> Dispatching 3 workers in PARALLEL
        ├── [w1-implementer]  strikethrough  (28 iters)  ┐
        ├── [w2-implementer]  task_lists     (26 iters)  ├─ concurrent
        └── [w3-implementer]  autolinks      (29 iters)  ┘
        ... all three call done() with structured summaries
[orch]  iter 5: think
[orch]  iter 6: delegate(verifier, criteria)
        └── [w4-verifier]  pytest + lint + grep + diff (5 iters)
[orch]  iter 7: done() ✓
```

All six verification criteria (§3) passed.

### 7b. v1 — antipattern surfaced

System prompt: original orchestrator (soft "INDEPENDENT subtasks should be dispatched in PARALLEL"; no explicit MUST, no counter-patterns named).

| Metric | Value |
|---|---|
| Workers spawned | 9 (1 orchestrator + 7 implementers + 1 verifier) |
| Orchestrator iters | 16 |
| Parallel batches fired | 1 (of 3 implementers, at orch iter ~9 — late in the trajectory) |
| Single delegate calls | 5 (recon + 2 single probes + 1 fix-up + 1 verifier) |
| `done()` calls from parallel workers | 0/3 — all 3 fell through to bare text |
| pytest result | 48/48 ✓ (recovered via fix-up + verifier workers) |
| Estimated cost @ Sonnet 4.6 | ~$1.29 |
| Wall time | ~8 min |

**Trajectory shape:**
```
orch: list_skills → think → write_plan → delegate(recon) → think → delegate(probe) →
      delegate(probe) → >>> PARALLEL: 3 implementers → all 3 fall through (no done()) →
      think → delegate(fix-up) → delegate(verifier) → done()
```

Same final outcome (pytest 48/48). But the orchestrator front-loaded with a recon worker and two single-feature probes before finally batching the last three implementations — half-parallel at best. Roughly **2× wall-clock** for the same task vs. v2.

### 7c. Findings

1. **Strong-wording lesson reproduces (consistent with Ep 5's task-wording finding).** v1's soft "INDEPENDENT subtasks should be dispatched in PARALLEL" was bypassed by the model's default safe-path bias ("let me do one and see how it goes"). v2's explicit "you MUST batch ≥2 independent subtasks in the SAME assistant turn" plus a named counter-pattern ("don't dispatch a recon worker as a first step") was followed on the first opportunity. **Operational rule for production orchestrators: parallelism instructions must be explicit and must name the antipattern.**

2. **`done()` reliability tracks task-shape AND parent-context.** v1's three parallel workers all fell through to bare text. v2's three all called `done()`. Difference: v1 gave them tightly-scoped tasks following a heavy recon; v2 gave each a full self-contained task with explicit success criteria. **The verifier-owns-completion architectural pattern (the orchestrator's `done()` fires after the verifier confirms, regardless of how each individual worker terminated) makes the whole run robust to individual worker done()-failures.** v1's run still passed all 6 criteria precisely because of this.

3. **Race condition on `md2html/extensions/__init__.py` (v2 only).** Three parallel workers each needed to register their extension in the same file. Each `edit(old_string, new_string)` reads the file at call time. Timeline:
   - w1 reads file, edits — first writer succeeds
   - w2 reads file (possibly stale), edits — old_string still present (timing-dependent), edit succeeds
   - w3 reads file, edits — old_string not found because w1/w2 changed the file. **Error returned.**
   - w3 reads file *again*, computes new old_string from current state, retries — succeeds.
   
   **Final file state: all three registrations land correctly.** The `edit` tool's exact-match semantics double as a soft optimistic-concurrency mechanism: collisions surface as errors (not silent corruption), and the agent's natural response (re-read, re-edit) handles the retry. Not robust enough for production scale, but works at the demo's worker count.

4. **Per-worker iter count is inversely correlated with parent-provided context.** v1's parallel workers were 3 iters each (orchestrator had pre-loaded context via recon). v2's parallel workers were 26–29 iters each (each did its own exploration). v2's higher per-worker iter count is the cost of skipping recon; the wall-clock win from concurrency more than compensates. **Design implication for production: there's a tradeoff between "orchestrator burns recon iters once" and "each worker burns exploration iters in parallel." The right answer depends on whether you can parallelize away the exploration cost.**

5. **Cache reuse is dominant.** v2 aggregate cache reads were 1.84M tokens (vs. 116K cache writes). Workers of the same agent_type share the cached system-prompt prefix; only the worker-specific task strings differ. **Per-worker context isolation is cheap when implemented this way** — most of the per-call payload is cached, not regenerated.

6. **No compaction fired.** `EP3_THRESHOLD=200000` set defensively (carried over from the Ep 5 compaction-server-tool gotcha; not strictly needed for Ep 6's task since no `web_search` is invoked). Per-worker contexts stayed well below the threshold.

7. **Structural answer to the done()-reliability gap from Eps 3–5:** the verifier worker owns the completion signal. Orchestrator's `done()` fires *after* the verifier reports a clean per-criterion pass. Whether each implementer worker called `done()` is no longer load-bearing for the run's correctness.

### 7d. Cost comparison vs. Ep 5 single-agent baselines

For approximate calibration only (n=1 each):

| Run | Task scope | Workers | Cost | Wall time |
|---|---|---|---|---|
| Ep 5 (locked v3b) | 1 feature (GH alerts) | 1 (single agent) | ~$1.44 | ~3–4 min |
| Ep 6 v2 (locked) | 3 features (strikethrough + task_lists + autolinks) | 5 (orch + 3 impl + verifier) | ~$1.28 | ~4 min |
| Ep 6 v1 | 3 features (same as v2) | 9 (orch + 7 impl + verifier) | ~$1.29 | ~8 min |

**Takeaway:** Ep 6 v2 implements 3 features at roughly the same total cost as Ep 5 implementing 1 feature. The per-worker context isolation lets the parallel implementers each work within a small cache footprint, amortizing the system-prompt-prefix cache write across all 3. Wall-clock-per-feature is dramatically better (3 features in ~4 min vs. extrapolated 9–12 min if Ep 5 did them serially).

---

## 8. Producer brief headlines

Build-spine principle (see `memory/feedback_build_spine_principle.md`): **the build is the deliverable; empirical observations are brief asides, not headlines.**

### Headlines (the build)

1. **`delegate(task, agent_type)` — 5 LOC of new tool.** The whole orchestration capability surface.
2. **`.agents/<name>.md` config primitive.** YAML frontmatter (tools allowlist, preloaded skills) + body (system prompt). Same shape as Ep 5's `SKILL.md`.
3. **`run_agent(task, agent_type)` — Ep 5's loop, function-extracted.** The orchestrator and every worker run through the same function; differences are entirely in the `AgentConfig`. Recursive shape.
4. **Parallel dispatcher — `ThreadPoolExecutor` over multiple `delegate` tool_uses in one assistant turn.** ~20 LOC. Matches Claude Code / Agent SDK's pattern.
5. **Role enforcement by toolset, not exhortation.** Orchestrator has no `read`/`write`/`edit`; verifier has no `write`/`edit`. Roles are structural, not prompt-conditional.

### Brief asides (~45 sec each)

1. **Aside 1 — task wording for the orchestrator.** Strong instructions + named counter-patterns get followed; soft instructions get bypassed. Same operational lesson as Ep 5's task-wording finding. Don't show the v1-vs-v2 trajectory diff on screen; the takeaway is the rule.
2. **Aside 2 — race recovery via `edit` exact-match semantics.** Parallel workers editing a shared file collide; `edit`'s strict matching surfaces collisions as errors rather than silent corruption; the agent's natural retry handles it. Teachable as one beat.

### What does NOT make the brief

- The v1 → v2 prompt-strengthening A/B in detail (referenced in aside 1 only).
- The `run_agent` refactor mechanics (mentioned conceptually as "Ep 5's loop, function-extracted"; not walked through).
- Per-worker token instrumentation, threading specifics, the worker-id logging prefix mechanism.
- The compaction-server-tool gotcha (not exercised in Ep 6's task).
- The dev-time SDK swap (continues from Eps 4–5; not new material).

---

## 9. Dev-time SDK note

Continues Eps 4/5's pattern: native Anthropic SDK + prompt caching during development. Two translations when shipping to the OpenAI-SDK companion code:
- `cache_control` (drop — no OpenAI equivalent)
- Server-side `web_search` — not used in Ep 6's task; if a future worker config preloads `research`, the same translation as Ep 5 applies.

Each worker has its own cache prefix (different system prompt per agent_type), so workers don't share cache with each other. Within a single worker's iterations, caching works the same as Ep 5.

---

## 10. Carryover gotchas from Ep 5 (read before implementing)

1. **`run_agent` must be reentrant.** Ep 5's loop relies on module-level mutables (`CURRENT_PLAN`, `LOADED_SKILLS`, `TOOLS_BY_NAME`, `messages`, token counters). Lifting these into `run_agent` function locals is the first refactor. Without it, concurrent workers will trample each other's state.
2. **Compaction-server-tool pair-splitting bug** still exists. Workers loading `research` skill and calling `web_search` can trip it if compaction fires. For Ep 6's task we don't use `web_search`, so we sidestep — but if any worker config in `.agents/` preloads `research`, set `EP3_THRESHOLD=200000` to disable compaction for that run.
3. **`done()` reliability is task-dependent.** Ep 5 showed `done()` is called reliably when the agent has a clean completion signal (pytest pass + ticked plan). Ep 6's design moves the completion signal to the verifier worker — orchestrator's done() fires after verifier reports success. Architectural answer to done()-reliability.
4. **Stdout interleaving across threads.** Python's `print` is not atomic at line granularity under contention. The worker-id prefix is one half of the fix; the other half is wrapping prints with a `threading.Lock` so the prefix and content travel as one print call.
5. **Skill purity discipline.** Workers must be able to load any skill independently (load_skill is in their toolset, skills are in `.skills/`). This is what makes worker spawning cheap. Don't break it.

---

## 11. Open questions / decisions deferred

- **Do we need a `researcher` worker type for any future Ep 6 variant?** Not for the canonical task. Could be added if a future episode reuses this scaffolding for a research-heavy task.
- **Per-worker token instrumentation.** Ep 5's `total_in`/`total_out` counters are module-level. For Ep 6, each worker needs its own counters (function-local), plus the top-level should aggregate across all workers for the run total. Add a `WorkerMetrics` dataclass.
- **Cost-of-orchestration vs. cost-of-single-agent.** If the orchestrated Ep 6 run is *more* expensive than Ep 5 doing all three features sequentially, that's a finding for the empirical section — orchestration's value is wall-clock, not necessarily dollars.
