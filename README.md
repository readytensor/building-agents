# Agents from First Principles

A 6-part technical video series produced by **Clyep** (originally planned as 5; extended to 6 after Ep 5 repivoted from multi-agent to skills, and orchestration moved to Ep 6). We build a working coding agent from scratch across the series, using each addition as a lens to examine the real architectural questions: what an agent is, why tools converge on small general primitives, why context matters more than prompts, what fails and why, when structure earns its complexity, and when one agent becomes many.

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
| 4   | **Planning & Thinking**  | What does it cost to make the agent legible? | Two new tools (write_plan + think) — and an honest cost result that recasts what planning is for |
| 5   | **Skills**                | How does it reach beyond its fixed toolkit without paying up-front? | A lazy-loaded capability library — the on-demand pattern Claude Code ships |
| 6   | **Orchestration**         | When is one agent the wrong shape?          | A clear framework for when multi-agent adds value vs. overhead        |

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
**Cliffhangers seeded:** Naive stop condition (returns in Ep 3), repetitive tool-schema definitions (cleaned in Ep 2), no history management (Ep 3), no planning or in-the-moment think tool (Ep 4).

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

### Episode 4 — Planning & Thinking

**Question:** What does it cost to make the agent legible — and what does that buy you?
**Limitation framed:** The Ep 3 agent works but its mid-flight intent is opaque. To know what it's trying to do you have to read every tool call. On long autonomous runs that's untenable.
**Addition (code):** Two new tools. **`write_plan(steps)`** — a Claude Code TodoWrite-style structured plan that lives in agent state (not message history) and is injected into the system prompt each iteration, persisting across compaction. **`think(thought)`** — a no-op tool that echoes back, forcing the model to externalize its thinking before action. The two have distinct purposes (state vs scratchpad), encoded in their `@tool` descriptions.
**Task:** A multi-step feature add — implementing reference-style markdown link support across the lexer, parser, renderer, and extension registry. Genuinely benefits from forward planning; a fair test of whether planning helps.
**Headline empirical result:** On this task, planning + think made the agent **more expensive**, not cheaper (+49% cost vs the Ep 3 baseline; +74% iterations). The intuitive "think before acting → fewer wasted steps" hypothesis is falsified. The episode lands this honestly.
**Closing abstraction:** Planning is a **legibility tax**, not a speedup. You pay more so a human (or another agent) can read the agent's intent before it acts. Worth it on long autonomous runs where supervision matters; net cost on short tasks. Reflection (loop detection that injects a "reconsider" prompt) was tried in development and cut — false positives dominated, no real spirals caught.
**Cliffhangers seeded:** The done()-reliability gap from Ep 3 is now *visible* — the structured plan ends with unchecked steps next to the agent's "I'm done" text. The agent's toolkit is also fixed — every tool sits in the system prompt forever, whether the current task needs it or not. Both threads continue into Eps 5 and 6.

### Episode 5 — Skills

**Question:** How does an agent reach beyond its fixed toolkit without paying for every possible capability up-front?
**Limitation framed:** Every tool the agent might ever want sits in the system prompt on every API call. Tool descriptions are tokens you're paying for, every turn, whether the tool is relevant to the current task or not. That doesn't scale past a handful of tools.
**Addition (code):** A **skills system** — composable, lazy-loadable bundles of procedural knowledge + tools, modeled on Claude Code's skill abstraction. Two new always-available tools: `list_skills()` (returns name + description for each available skill — cheap) and `load_skill(name)` (parses the named `SKILL.md`, appends the body to the dynamic system-prompt block, registers any tools the skill provides). A `.skills/<name>/SKILL.md` file format (YAML frontmatter + body). A skill-provided tools registry so that tools only appear in the agent's toolkit when their owning skill is loaded. Ep 4's plan-injection mechanism is extended to also carry loaded-skill bodies.
**Task:** Add GitHub-flavored alerts (`> [!NOTE]`, etc.) to md2html. The task explicitly directs the agent to check GitHub's docs for the spec — anchoring a `research` skill (web_search + fetch_url) as the demo's load-bearing skill. A `verification` skill ships alongside as a second library entry.
**Closing abstraction:** Skills shift the agent from "fixed toolkit" to "discoverable on-demand capability library." The base toolkit stays compact; specialized capability arrives on demand, declared in plain markdown. This is the pattern Claude Code and the Agent SDK ship in production.

### Episode 6 — Orchestration

**Question:** When is one agent the wrong shape for a problem — and what does the smallest interesting multi-agent shape look like?
**Limitation framed:** Three independent subtasks in one ticket all compete for the same context, the same toolset, and the same thread. The agent does them serially even when they don't depend on each other.
**Addition (code):** A **`delegate(task, agent_type)` tool** that spawns a fresh worker agent with the toolset + skills declared in `.agents/<agent_type>.md`. Ep 5's main loop is refactored into a reentrant `run_agent(task, agent_type)` function used recursively — the orchestrator and every worker run through the same function, parameterized by `AgentConfig`. A `ThreadPoolExecutor` parallel dispatcher: when the orchestrator's assistant turn includes multiple `delegate` tool_use blocks, they fan out concurrently and return results together in the next turn. The orchestrator gets no codebase-mutation tools (no `read`/`write`/`edit`/`bash`/`grep`) — all work goes through workers. A verifier worker has no `write`/`edit` either — role enforced by toolset, not exhortation.
**Task:** Add three GFM features to md2html at once (strikethrough, task lists, autolinks). Naturally parallelisable; the orchestrator's value is *visible* in the trajectory — three concurrent `delegate` tool_uses in a single turn.
**Closing abstraction:** Orchestration isn't a new loop. It's Ep 5's loop, recursive, with one new tool and one new config primitive. The orchestrator IS a worker. The mechanism matches what Claude Code and the Agent SDK ship in production (isolated worker context, depth capped at 1, parallel batched-tool-call dispatch). The architecture is complete; what wraps around it — durable execution, guardrails, production ops — is a different series.

---

## Code progression at a glance

|                | Ep 1                    | Ep 2                            | Ep 3                           | Ep 4                                   | Ep 5                                            | Ep 6                                                       |
| -------------- | ----------------------- | ------------------------------- | ------------------------------ | -------------------------------------- | ----------------------------------------------- | ---------------------------------------------------------- |
| Loop           | naive `while`           | same                            | same                           | same                                   | same                                            | **`run_agent(task, agent_type)` — reentrant, recursive**   |
| Tools          | `bash`                  | + `read`, `write`, `edit`, `grep` | + (no new tools)             | + `write_plan` + `think`               | + `list_skills` + `load_skill`                  | + `delegate`                                               |
| Tool schemas   | hand-written            | `@tool` helper                  | same                           | same                                   | same                                            | same                                                       |
| Stop condition | no tool calls → break   | same                            | **`done()` / `TaskComplete`**  | same                                   | same                                            | same; orchestrator's `done()` fires after verifier confirms |
| History        | raw list                | raw list                        | **rolling-summary compaction** | same                                   | same                                            | per-worker                                                 |
| Planning       | none                    | none                            | none                           | **`write_plan` + `think`**             | inherited                                       | inherited                                                  |
| Skill library  | n/a                     | n/a                             | n/a                            | n/a                                    | **`.skills/<name>/SKILL.md` + dynamic injection** | inherited; workers can preload skills via their config     |
| Agent configs  | n/a                     | n/a                             | n/a                            | n/a                                    | n/a                                             | **`.agents/<name>.md` config primitive (frontmatter + body)** |
| Agents         | 1                       | 1                               | 1                              | 1                                      | 1                                               | **N (1 orchestrator + parallel workers)**                  |
| Sandbox        | 5-line `SandboxContext` | same                            | same                           | same                                   | same                                            | same; workers share the parent's sandbox cwd               |

By Ep 6, the code is a recognizable _minimal subset_ of the architectural pattern that powers production agent systems — loop, tools, compaction, done tool, planning + think tools, skills library, multi-agent orchestration with parallel dispatch — with all the production scaffolding deliberately removed.

---

## Scope and non-goals

**The framing principle:**

> _Things that change the agent's shape are in scope. Things that wrap around it aren't._

### In scope (changes the agent's shape)

- The loop, tools, history management, stop conditions, planning and in-the-moment thinking, multi-agent topology.

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
- **Naturally extensible** through the existing extension hook protocol — Eps 2, 4, 5, and 6 all add new extensions (escaped-backtick fix, reference-style links, GitHub alerts, three GFM features in parallel). The protocol earns its keep across the series.

### Task escalation across episodes

| Ep  | Task on `md2html`                                                                                                                 | Why it forces the episode's lesson                                                   |
| --- | --------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| 1   | Explore the repo and explain what it does                                                                                         | Multiple chained `bash` calls; loop is visibly iterating                             |
| 2   | Fix a planted bug — parser mishandles escaped backticks (one character missing from the escapable-character set)                  | Needs read + edit + run pytest — earns multi-tool design                             |
| 3   | Refactor across modules — rename `Node` → `ASTNode` across 5 files / ~58 occurrences                                              | Long history of file contents naturally fills context; agent visibly loses thread; the compaction sweet spot vs. "hallucinated success" failure becomes legible |
| 4   | Add reference-style markdown link support — feature-add touching lexer + parser + renderer + extension registry                   | Multi-step structure where a human would naturally plan; fair test of "does planning help?" (empirical answer: cost goes up, legibility is what you actually buy) |
| 5   | Add GitHub-flavored alerts (`> [!NOTE]`, etc.) to md2html — implemented as a new extension                                        | Task explicitly directs the agent to check GitHub's docs — anchors the `research` skill (web_search + fetch_url) as a clean discover → load → use → done demo |
| 6   | Add three independent GFM features at once (strikethrough, task lists, autolinks)                                                  | Three independent subtasks = natural parallel decomposition; the orchestrator's value is visible in the trajectory (three concurrent `delegate` calls in one turn) |

### Spec

- **Toy codebase spec:** [`spec/md2html.md`](./spec/md2html.md) — architecture, markdown subset, extensions, CLI, file-by-file responsibilities, Ep 1's `initial/` definition. Authoritative for the toy codebase.
- **Per-episode specs** (define what changes from the previous episode — agent additions and `initial/` state divergences):
  - **Episode 2:** [`spec/episode-02.md`](./spec/episode-02.md) — adds 4 tools + `@tool` decorator; plants escaped-backtick bug in parser.py; adds `escaped_backticks` fixture pair.
  - **Episode 3:** [`spec/episode-03.md`](./spec/episode-03.md) — adds done tool + rolling-summary compaction (~50 LOC); task is renaming `Node` → `ASTNode` across 5 files / 58 occurrences; `initial/` is clean (no planted modifications). Includes a non-negotiable 4-step verification procedure (pytest + case-sensitive grep counts + diff). **Implemented + 7 trajectories captured + producer brief written.** Parameter sweep revealed a "hallucinated success" failure mode at aggressive compaction settings (5K threshold + Keep 2) — the agent confidently calls `done()` while leaving the task half-finished. This is the bridge to Ep 4.
  - **Episode 4:** [`spec/episode-04.md`](./spec/episode-04.md) — adds `write_plan` (TodoWrite-style structured plan in agent state, injected into the system prompt) + `think` (no-op echo for externalized thinking). Reflection was tried and cut. Task: implement reference-style markdown links across the markdown pipeline. **Implemented + recorded baseline-vs-planning A/B + producer brief written.** Empirical observation (now framed as a design consideration per the build-spine principle, not a dramatic headline): planning + think made the agent +49% more expensive, +74% more iterations, with the same end result — useful input when deciding whether to add planning to your own agent; legibility is what you actually buy on long autonomous runs.
  - **Episode 5:** [`spec/episode-05.md`](./spec/episode-05.md) — adds the skills system: `list_skills` + `load_skill` + the `.skills/<name>/SKILL.md` file format + a skill-provided tools registry; extends Ep 4's dynamic system-prompt mechanism to carry loaded-skill bodies. Task: add GitHub-flavored alerts to md2html. Two skills ship in `.skills/`: `research` (anchored by the task) and `verification`. **Implemented + 6 trajectories recorded + producer brief written + skills library overview written.** Brief aside in the producer brief on task wording as the variable that decides whether the agent reaches for skills (strong wording → reliable use; soft wording → bypassed).
  - **Episode 6:** [`spec/episode-06.md`](./spec/episode-06.md) — adds the orchestration mechanism: `delegate(task, agent_type)` tool, `.agents/<name>.md` config primitive (frontmatter + body, parsed by the same YAML helper as Ep 5's `SKILL.md`), `run_agent(task, agent_type)` (Ep 5's loop, function-extracted; orchestrator and workers are the same function, parameterized by `AgentConfig`), and a `ThreadPoolExecutor` parallel dispatcher (multiple `delegate` tool_uses in one assistant turn run concurrently — matches the Claude Code / Agent SDK pattern). Task: add three GFM features at once (strikethrough, task lists, autolinks). Two worker configs ship in `.agents/`: `implementer` and `verifier`. **Implemented + 2 trajectories recorded (v1 antipattern + v2 canonical) + producer brief written.** Empirical findings (brief asides in the producer brief): the strong-wording lesson from Ep 5 generalizes to orchestrator prompts; `edit`'s exact-match semantics act as soft optimistic-concurrency when parallel workers collide on a shared file. **Season finale of the build arc.**

---

## Capstone (deferred)

A 7th "documentary" episode — point the finished Ep 6 agent at a real engineering task and show what happens, failures included, unedited — is on the table but **not committed**. Decision point is **after Episode 6 ships**: if the arc lands without it, skip it. If kept, it's a looser companion piece, not bound to the same Clyep production cadence as the main 6 episodes.

The reasoning: a clean victory-lap demo would just duplicate what Ep 1–6 already proved. A documentary-style real run ("here's what happened, including what broke") is the only framing that adds value.

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
    ├── 04-planning-thinking/
    ├── 05-skills/
    └── 06-orchestration/
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

- **Persistent visual artifact across the series:** the animated for-loop. It starts simple in Ep 1 (`while → invoke → tool → result → repeat`) and gains layers in each episode — tools halo (Ep 2), done-ring + compaction band (Ep 3), planner ring + think bubble (Ep 4), skills rack (Ep 5) — until Ep 6 shows the multi-agent topology with parallel-worker silhouettes spawned from a `delegate` edge. That's the artifact the viewer subconsciously tracks across episodes.
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
│       ├── 04-planning-thinking/{agent.py, README.md, initial/}
│       ├── 05-skills/{agent.py, README.md, initial/}
│       └── 06-orchestration/{agent.py, README.md, initial/}
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
