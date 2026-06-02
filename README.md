# Agents from First Principles

Build a working coding agent from scratch — from a plain `while` loop with a single tool, all the way to multi-agent orchestration. No frameworks: just Python and a model API.

This is the companion code for the **"Agents from First Principles"** video series by Clyep. Each episode adds one idea, in code, on top of the last — and the diff between one episode and the next is the lesson.

## Who this is for

Engineers comfortable with Python and calling an LLM API. No prior agent-building experience required. By the end you'll be able to build a basic agent, extend it deliberately, debug it when it breaks, and critically evaluate any agent system you encounter.

The worked example is a **coding agent** — the cleanest domain to learn in: a tight feedback loop and a small tool surface. The same ideas carry over to research agents, browser automation, and data pipelines.

## The series

| #   | Episode               | The question                                | What you build                                                              |
| --- | --------------------- | ------------------------------------------- | -------------------------------------------------------------------------- |
| 1   | The Loop              | What is an agent?                           | A minimal agent: a `while` loop + one `bash` tool                          |
| 2   | Tools                 | How does it actually do things?             | General primitives (`read` / `write` / `edit` / `grep`) + a tiny `@tool` helper |
| 3   | Context               | Why does it get worse on long tasks?        | Rolling-summary compaction to keep long runs affordable                    |
| 4   | Planning & Thinking   | What does it cost to make the agent legible? | `write_plan` + `think`, plus a dynamic system prompt                        |
| 5   | Skills                | How does it reach beyond its fixed toolkit? | A lazy-loaded skills system (`list_skills` / `load_skill` + `SKILL.md`)     |
| 6   | Orchestration         | When is one agent the wrong shape?          | `delegate` + worker configs + parallel multi-agent dispatch                 |

Each episode follows the same rhythm: one question, one limitation, one addition in code, one before/after.

## Quickstart

```bash
git clone https://github.com/readytensor/building-agents
cd building-agents
```

Install with `uv` (recommended):

```bash
uv sync
cp .env.example .env          # add your OPENAI_API_KEY
```

…or with plain `pip`:

```bash
python -m venv .venv
source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e .
cp .env.example .env          # add your OPENAI_API_KEY
```

Run an episode:

```bash
cd episodes/01-loop
python agent.py
```

## How the code is organized

```
building-agents/
├── episodes/
│   ├── 01-loop/
│   │   ├── agent.py      # the episode's agent — start here
│   │   ├── initial/      # pristine starting copy of the example project
│   │   └── sandbox/      # where the agent works (recreated every run)
│   ├── 02-tools/
│   ├── 03-context/
│   ├── 04-planning-thinking/
│   ├── 05-skills/
│   └── 06-orchestration/
├── run.py               # optional harness to record a run (see below)
├── capture.py           # terminal recorder used by run.py --capture
├── pyproject.toml
└── .env.example
```

Each episode is **self-contained** — `cd` into it and run `python agent.py`. No branch switching.

**`initial/` → `sandbox/`.** Every `agent.py` begins by wiping `sandbox/` and copying `initial/` into it, so each run starts from an identical clean state. `initial/` is never modified; the agent only works inside `sandbox/`. After a run, see what it changed:

```bash
diff -r initial sandbox
```

**The diff between episodes is the lesson.** Compare two agents to see exactly what each idea added:

```bash
diff episodes/01-loop/agent.py episodes/02-tools/agent.py
```

## Recording a run (optional)

`python agent.py` runs the agent on its own. If you want to capture what happened — to compare runs or inspect the agent's path — use the `run.py` harness instead (from the repo root):

```bash
python run.py --cwd episodes/01-loop            # record the tool-call sequence to logs/<timestamp>/
python run.py --cwd episodes/01-loop --capture  # also save the full terminal output
```

Each run gets its own timestamped folder under the episode's `logs/`, so you can run the same task repeatedly and compare how the agent's path and tool-call count vary from run to run. `capture.py` is the underlying terminal recorder and also works standalone on any command (e.g. `python capture.py -- pytest -q`).

## The example project: `md2html`

Every episode points the agent at the same small codebase — `md2html`, a Markdown-to-HTML CLI with real module boundaries (lexer → parser → renderer → extensions → CLI) and a pytest suite. Small enough to follow, structured enough that each episode's task lands on a real seam — and the tests let the agent verify its own work instead of just claiming success.

## Provider portability

The code uses the `openai` Python package against the **Chat Completions API**, so it runs against any OpenAI-compatible endpoint — just set `LLM_BASE_URL` and `LLM_AGENT_MODEL` in `.env`. Compatible providers include OpenAI, Groq, Together, Mistral, DeepSeek, Ollama, vLLM, and OpenRouter. We avoid provider-specific features so the same code stays portable.

## Scope

This series is about the **architectural core** of how agents work: the loop, tools, context management, planning, skills, and multi-agent topology. Deliberately out of scope — each its own topic — are production ops, durable execution, full guardrails, framework reviews, and model training/RL.
