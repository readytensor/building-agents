# Agents from First Principles

A 5-part technical video series produced by **Clyep**. We build a working coding agent from scratch across the series, using each addition as a lens to examine the real architectural questions: what an agent is, why tools converge on small general primitives, why context matters more than prompts, what fails and why, when structure earns its complexity, and when one agent becomes many.

The canonical original brief is in [`building-agents-series.v1.md`](./building-agents-series.v1.md). This README is the working source of truth — it carries the brief forward with all design decisions made since.

---

## What the series is

Engineers and technical practitioners who use agents, are building them, or want to read new agent releases critically come away with a durable mental model of how agents work, grounded in a simple progressive implementation. By the end, viewers can build a basic agent, extend it deliberately, debug it when it breaks, and evaluate any agent system they encounter — production or otherwise — with real conceptual footing.

The worked example is a **coding agent**. It's the cleanest domain to teach in: tight feedback loop, small tool surface, strong model performance. The same architectural lessons transfer directly to research agents, browser automation, and data pipelines.

**Assumed audience:** Python fluency, comfort calling LLM APIs. No prior agent-building experience required.

---

## Series arc

| #   | Episode                   | Core question                               | Standalone value                                                      |
| --- | ------------------------- | ------------------------------------------- | --------------------------------------------------------------------- |
| 1   | **The Loop**              | What is an agent?                           | A working agent the viewer can run and modify today                   |
| 2   | **Tools**                 | How does it actually do things?             | An agent with real capabilities; intuition for tool design            |
| 3   | **Context**               | Why does it get worse on longer tasks?      | The most important practical insight in the series                    |
| 4   | **Planning & Reasoning**  | What does it cost to make the agent legible? | Two reasoning-strategy tools — and an honest cost result that recasts what planning is for |
| 5   | **Orchestration**         | When is one agent the wrong shape?          | A clear framework for when multi-agent adds value vs. overhead        |

Each episode follows the same internal rhythm: **one question, one limitation, one addition (in code), one before/after, one abstraction** — closing with "this is the same pattern real systems use, just with more machinery."

---

## Episode plan

### Episode 1 — The Loop

**Question:** What is an agent?
**Limitation framed:** None yet — we're building from zero.
**Addition (code):** Raw `openai` SDK call inside a `while` loop, **one tool: `bash`**, naive stop condition (no tool calls → break). ~60–80 lines.
**Light-touch concern:** A 5-line `SandboxContext` bounding `bash` to a working directory. Acknowledged on screen, not the focus.
**Task:** Point the agent at a small unfamiliar directory and ask it to explain what the code does. Multiple chained `bash` calls; concrete output the viewer can see.
**Closing abstraction:** This is what Claude Code is doing right now in your terminal — same loop, more machinery.
**Cliffhangers seeded:** Naive stop condition (returns in Ep 3), repetitive tool-schema definitions (cleaned in Ep 2), no history management (Ep 3), no planning or in-the-moment reasoning tool (Ep 4).

### Episode 2 — Tools

**Question:** How does the agent actually do things?
**Limitation framed:** With only `bash`, the agent works but every operation goes through one channel — and writing new tool schemas by hand from Ep 1 is already tedious.
**Addition (code):** A small set of general primitives (`read`, `write`, `grep` alongside `bash`); a tiny `@tool` decorator / schema helper to eliminate JSON-schema boilerplate; **skills** introduced as named Python helpers composed from primitives — not a new abstraction, just reusable functions.
**Task:** Fix a small bug in the same repo from Ep 1 — read several files, propose the fix, write it back, run the test via `bash`.
**Closing abstraction:** A few general tools beat many narrow ones. Production systems converge here for a reason.
**Cliffhangers seeded:** Tools that return big outputs will start to bloat context; the agent still has no real way to signal completion.

### Episode 3 — Context

**Question:** Why does the same agent succeed on some tasks and fail on others?
**Limitation framed:** A long task fills the context window. The agent loses the thread, repeats steps, or forgets the original goal. Separately, sometimes it "falls silent" and the naive stop fires prematurely.
**Additions (code):** **Rolling-summary compaction** — when message history crosses a token threshold, the agent summarizes older turns and continues from there. **Done tool** — an explicit `done(message)` that raises `TaskComplete`, replacing the naive stop from Ep 1.

These two are paired because both serve the same theme: _making long-running tasks reliable_. Compaction keeps the agent from losing what was said; the done tool keeps it from quitting before the work is finished.

**Task:** A multi-file refactor across the repo. File contents legitimately stack up in history; the naive agent loses coherence mid-task. With compaction + done tool, it gets through cleanly.
**Closing abstraction:** Agent capability is mostly context quality, not prompt cleverness. Performance is downstream of what the model can see, not what you told it at the start.
**Cliffhangers seeded:** Even with managed context, the agent can still run in circles, hallucinate progress, or drift off-task — different class of failure, addressed next.

### Episode 4 — Planning & Reasoning

**Question:** What does it cost to make the agent legible — and what does that buy you?
**Limitation framed:** The Ep 3 agent works but its mid-flight intent is opaque. To know what it's trying to do you have to read every tool call. On long autonomous runs that's untenable.
**Addition (code):** Two reasoning-strategy tools. **`write_plan(steps)`** — a Claude Code TodoWrite-style structured plan that lives in agent state (not message history) and is injected into the system prompt each iteration, persisting across compaction. **`think(thought)`** — a no-op tool that echoes back, forcing the model to externalize reasoning before action. The two have distinct purposes (state vs scratchpad), encoded in their `@tool` descriptions.
**Task:** A multi-step feature add — implementing reference-style markdown link support across the lexer, parser, renderer, and extension registry. Genuinely benefits from forward planning; a fair test of whether planning helps.
**Headline empirical result:** On this task, planning + think made the agent **more expensive**, not cheaper (+49% cost vs the Ep 3 baseline; +74% iterations). The intuitive "think before acting → fewer wasted steps" hypothesis is falsified. The episode lands this honestly.
**Closing abstraction:** Planning is a **legibility tax**, not a speedup. You pay more so a human (or another agent) can read the agent's intent before it acts. Worth it on long autonomous runs where supervision matters; net cost on short tasks. Reflection (loop detection that injects a "reconsider" prompt) was tried in development and cut — false positives dominated, no real spirals caught.
**Cliffhangers seeded:** The done()-reliability gap from Ep 3 is now *visible* — the structured plan ends with unchecked steps next to the agent's "I'm done" text. One agent is still a bottleneck for tasks with conflicting responsibilities or genuine parallelism. Both threads continue into Ep 5.

### Episode 5 — Orchestration

**Question:** When is one agent the wrong shape for a problem?
**Limitation framed:** A task that genuinely strains the single-agent architecture — context overload, conflicting responsibilities, or parts of the task that benefit from different modes of operation.
**Addition (code):** A second agent instance with its own system prompt and tool subset; a `delegate(subtask)` tool on the parent that spawns a child; minimal message-passing between them.
**Task:** A larger task spanning multiple subdirectories or concerns — planner decomposes, executors handle subtasks. The episode also shows where this _doesn't_ help: on a small task, orchestration is just routing overhead.
**Closing abstraction:** Multi-agent helps when tasks decompose cleanly, when parallelism matters, or when context boundaries are real constraints. When those conditions don't hold, it's overhead. The episode closes with the genuine open questions in the field — coordination failures, trust between agents, context handoffs — rather than pretending they're solved.

---

## Code progression at a glance

|                | Ep 1                    | Ep 2                            | Ep 3                           | Ep 4                                   | Ep 5                        |
| -------------- | ----------------------- | ------------------------------- | ------------------------------ | -------------------------------------- | --------------------------- |
| Loop           | naive `while`           | same                            | same                           | same                                   | same                        |
| Tools          | `bash`                  | `bash`, `read`, `write`, `grep` | + (no new tools)               | + `write_plan` + `think`               | + `delegate`                |
| Tool schemas   | hand-written            | `@tool` helper                  | same                           | same                                   | same                        |
| Stop condition | no tool calls → break   | same                            | **`done()` / `TaskComplete`**  | same                                   | same                        |
| History        | raw list                | raw list                        | **rolling-summary compaction** | same                                   | per-agent                   |
| Planning       | none                    | none                            | none                           | **plan + think (reflect tried, cut)**  | inherited                   |
| Agents         | 1                       | 1                               | 1                              | 1                                      | **N (planner + executors)** |
| Sandbox        | 5-line `SandboxContext` | same                            | same                           | same                                   | same                        |

By Ep 5, the code is a recognizable _minimal subset_ of the architectural pattern that powers production agent systems — loop, tools, compaction, done tool, planning + reasoning tools, orchestration — with all the production scaffolding deliberately removed.

---

## Scope and non-goals

**The framing principle:**

> _Things that change the agent's shape are in scope. Things that wrap around it aren't._

### In scope (changes the agent's shape)

- The loop, tools, history management, stop conditions, planning and in-the-moment reasoning, multi-agent topology.

### Light touch only (acknowledged when it can't be ignored)

- **Sandbox / isolation.** ~60 seconds in Ep 1 when `bash` appears. Giving the agent shell access is a security decision whether you acknowledge it or not — but the full topic is its own series.

### Out of scope (separate series, or never)

- **Prompt engineering at the token level.** Context engineering is the craft; prompt tuning is downstream.
- **Framework reviews** (LangChain, LlamaIndex, CrewAI). Those are implementations of the patterns covered, not the patterns.
- **Model training, RL, evals.** The series takes the model as given.
- **Production ops.** Retries, rate limits, cost tracking, monitoring, deployment.
- **Durable execution.** Checkpointing agent state, resuming across restarts, hour/day-long tasks. Separate series candidate.
- **Full guardrails.** Content filtering, tool-permission gating, auth, multi-tenant isolation. Separate series candidate.

Each exclusion is deliberate. The series promises depth on one thing: the architectural core of how agents work.

---

## Code conventions

- **Language:** Python 3.11+
- **LLM SDK:** The `openai` Python package against the **Chat Completions API** (`client.chat.completions.create(..., tools=[...])`). Not the Responses API — Responses is OpenAI-only and not portable.
- **Provider-agnostic.** The Chat Completions request/response shape is mimicked by Groq, Together, Mistral, DeepSeek, Ollama, vLLM, OpenRouter, and most local model servers. Viewers can point the same code at whatever model endpoint they have access to by overriding `base_url`. This is why we avoid provider-specific features (Anthropic prompt caching, Google thinking budgets, OpenAI reasoning model parameters).
- **Episode 1 line budget:** ~60–80 lines including imports.
- **Progressive build.** Each episode's code is a small, identifiable diff on top of the previous episode — not a rewrite. Each episode's code runs independently as a tagged commit in the companion repo.

---

## Working example

### Toy codebase: `md2html`

A small but properly-structured **Markdown-to-HTML CLI tool**. Chosen because its pipeline naturally factors into real module boundaries even at small scale, giving every episode something genuine to exercise:

````
md2html/
├── pyproject.toml
├── README.md
├── md2html/
│   ├── __init__.py
│   ├── cli.py                  # argparse + entry point
│   ├── lexer.py                # markdown → token stream
│   ├── parser.py               # token stream → AST
│   ├── renderer.py             # AST → HTML
│   ├── extensions/
│   │   ├── __init__.py
│   │   ├── tables.py
│   │   ├── code_blocks.py      # fenced ``` with language tag
│   │   └── footnotes.py
│   └── utils.py
└── tests/
    ├── test_lexer.py
    ├── test_parser.py
    ├── test_renderer.py
    └── fixtures/
        ├── basic.md
        ├── tables.md
        └── ...
````

Why this fits the series:

- **Real module boundaries** (lexer / parser / renderer / extensions / CLI) — not arbitrary splits. Each episode's task lands on actual seams.
- **Plant-a-bug surface is large.** Escaped backticks, malformed nested-list HTML, misaligned tables, footnote-numbering off-by-one — all natural and localizable.
- **Has a running test suite** that the agent can invoke via `bash pytest`. The agent verifies its own work — more honest than "trust the agent."
- **Naturally extensible** for Ep 5 — "add LaTeX output as a second renderer" is real multi-module work.

### Task escalation across episodes

| Ep  | Task on `md2html`                                                                                                                 | Why it forces the episode's lesson                                                   |
| --- | --------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| 1   | Explore the repo and explain what it does                                                                                         | Multiple chained `bash` calls; loop is visibly iterating                             |
| 2   | Fix a planted bug (e.g., lexer mishandles escaped backticks)                                                                      | Needs read + edit + run pytest — earns multi-tool design                             |
| 3   | Refactor across modules (e.g., rename `Token` → `Node` across lexer/parser/renderer/tests; or change an extension hook signature) | Long history of file contents naturally fills context; agent visibly loses thread    |
| 4   | Add reference-style markdown link support — feature-add that touches lexer + parser + renderer + extension registry              | Multi-step structure where a human would naturally plan; fair test of "does planning help?" (empirical answer: cost goes up, legibility is what you actually buy) |
| 5   | Add LaTeX as a second output format                                                                                               | Touches CLI flag, new renderer, possibly extension hooks, tests — real decomposition |

### Spec

- **Toy codebase spec:** [`spec/md2html.md`](./spec/md2html.md) — architecture, markdown subset, extensions, CLI, file-by-file responsibilities, Ep 1's `initial/` definition. Authoritative for the toy codebase.
- **Per-episode specs** (define what changes from the previous episode — agent additions and `initial/` state divergences):
  - **Episode 2:** [`spec/episode-02.md`](./spec/episode-02.md) — adds 4 tools + `@tool` decorator; plants escaped-backtick bug in parser.py; adds `escaped_backticks` fixture pair.
  - **Episode 3:** [`spec/episode-03.md`](./spec/episode-03.md) — adds done tool + rolling-summary compaction (~50 LOC); task is renaming `Node` → `ASTNode` across 5 files / 58 occurrences; `initial/` is clean (no planted modifications). Includes a non-negotiable 4-step verification procedure (pytest + case-sensitive grep counts + diff). **Implemented + 7 trajectories captured + producer brief written.** Parameter sweep revealed a "hallucinated success" failure mode at aggressive compaction settings (5K threshold + Keep 2) — the agent confidently calls `done()` while leaving the task half-finished. This is the bridge to Ep 4.
  - **Episode 4:** [`spec/episode-04.md`](./spec/episode-04.md) — adds `write_plan` (TodoWrite-style structured plan in agent state, injected into the system prompt) + `think` (no-op echo for externalized reasoning). Reflection was tried and cut. Task: implement reference-style markdown links across the markdown pipeline. **Implemented + recorded baseline-vs-planning A/B + producer brief written.** Headline finding: planning + think made the agent +49% more expensive, +74% more iterations, with the same end result — recasting planning as a "legibility tax" rather than a speedup.
  - Episode 5: to be written when prepared.

---

## Capstone (deferred)

A 6th "documentary" episode — point the finished agent at a real engineering task and show what happens, failures included, unedited — is on the table but **not committed**. Decision point is **after Episode 4**: if the arc lands without it, skip it. If kept, it's a looser companion piece, not bound to the same Clyep production cadence as the main 5 episodes.

The reasoning: a clean victory-lap demo would just duplicate what Ep 1–5 already proved. A documentary-style real run ("here's what happened, including what broke") is the only framing that adds value.

---

## Companion code repo

The series ships with a **public GitHub repo separate from this planning workspace**, containing the agent code for each episode and the toy codebase it operates on.

### Structure

```
agents-from-first-principles/        # public companion repo
├── README.md
├── pyproject.toml
├── .env.example
├── .gitignore                       # includes episodes/*/sandbox/
└── episodes/
    ├── 01-loop/
    │   ├── agent.py                 # ~60–80 lines
    │   ├── initial/                 # pristine starting state of the toy codebase (committed)
    │   ├── sandbox/                 # agent's working directory (gitignored, recreated each run)
    │   └── README.md                # how to run, env vars expected
    ├── 02-tools/
    ├── 03-context/
    ├── 04-planning-reasoning/
    └── 05-orchestration/
```

**Each episode is self-contained.** Viewer can `cd episodes/03-context && python agent.py` and see exactly that episode's agent. No git checkout dance, no branch switching.

**The diff between consecutive episodes is the lesson.** `diff episodes/01-loop/agent.py episodes/02-tools/agent.py` shows what changed, structurally.

### Running an episode (`initial/` → `sandbox/`)

Every `agent.py` opens with a deterministic sandbox reset — the agent always starts on a clean copy of the episode's `initial/` state:

```python
import shutil
from pathlib import Path

INITIAL = Path("initial")
SANDBOX = Path("sandbox")
if SANDBOX.exists():
    shutil.rmtree(SANDBOX)
shutil.copytree(INITIAL, SANDBOX)
```

- `initial/` is the **pristine template** (committed to git, never modified by the agent).
- `sandbox/` is the **agent's bounded working directory** (gitignored, wiped and recreated on every run).
- The agent's `SandboxContext` points at `sandbox/`, not `initial/` — paths escaping `sandbox/` raise.
- After a run, `sandbox/` contains the agent's work. Inspecting changes: `diff -r initial sandbox`.
- Toy code inside `sandbox/` uses the parent venv that's running `agent.py` — no nested virtualenvs.

### What lives outside the companion repo

Reference materials and visual/conceptual inspiration for the series are tracked in this planning workspace's `tmp/` directory (see below) but are **not** part of the deliverable.

---

## Production notes (Clyep)

Per Clyep's production strengths (`tmp/about-clyep/clyep-video-production-strengths.txt`):

- **Persistent visual artifact across the series:** the animated for-loop. It starts simple in Ep 1 (`while → invoke → tool → result → repeat`) and gains layers in each episode — done-tool ring, compaction layer, planner ring — until Ep 5 shows the multi-agent topology. That's the artifact the viewer subconsciously tracks across episodes.
- **No AI avatars or talking heads.** Content is technical artifacts + AI-generated narration.
- **Narrative discipline:** cold-open hook → mechanism → insight → payoff, every episode.
- **Series-grade visual continuity.** Palette, typography, motion language designed once for the whole series at the start of Ep 1.

---

## Planning workspace layout

This directory is the **planning workspace** — separate from the public companion code repo (see above).

```
building-agents/
├── README.md                              # this file — working source of truth
├── CLAUDE.md                              # operational guidance for Claude Code sessions
├── building-agents-series.v1.md           # original series brief (snapshot)
├── spec/                                  # spec docs for what gets built in the companion repo
│   └── md2html.md                         # the toy codebase spec (architecture, subset, extensions, CLI)
├── code/                                  # companion repo content (lives here until split out)
│   ├── README.md
│   ├── pyproject.toml
│   ├── .env.example
│   ├── .gitignore                         # episodes/*/sandbox/ is ignored
│   └── episodes/
│       ├── 01-loop/{agent.py, README.md, initial/}
│       ├── 02-tools/{agent.py, README.md, initial/}
│       ├── 03-context/{agent.py, README.md, initial/}
│       ├── 04-planning-reasoning/{agent.py, README.md, initial/}
│       └── 05-orchestration/{agent.py, README.md, initial/}
└── tmp/                                   # reference material — NOT the deliverable
    ├── about-clyep/                       # Clyep brand, ICP, production strengths
    │   ├── 1-What-is-Clyep.txt
    │   ├── 4-Clyep ICP.md
    │   └── clyep-video-production-strengths.txt
    ├── agent-sdk/                         # Browser Use's open-source bu-agent-sdk (inspiration)
    │   ├── bu_agent_sdk/
    │   └── README.md
    └── blog/                              # "The Bitter Lesson of Agent Frameworks" — Browser Use blog post + diagrams
        ├── blog.txt
        ├── header.png                     # the agent for-loop diagram
        ├── 99model.png
        ├── inversion.png
        ├── 02-done-tool-comparison.excalidraw.png
        ├── 03-llm-providers.excalidraw.png
        └── sdk.png
```

Everything in `tmp/` is for reference and visual/conceptual inspiration. Code shapes, framings, and diagram conventions are fair to _adapt_. Nothing in `tmp/` should be copied verbatim.
