# Agents from First Principles — companion code

Code for the 5-episode "Agents from First Principles" video series produced by Clyep. Each episode is a self-contained agent built progressively on top of the previous one. By the end of the series, the codebase is a recognizable minimal subset of what powers production agent systems.

> This directory currently lives inside the planning workspace at `building-agents/code/`. When ready, it will be split out as its own public repo. Authoritative spec and planning docs live in the parent workspace.

## Setup

With `uv` (recommended):

```bash
uv sync
cp .env.example .env               # fill in OPENAI_API_KEY
```

With plain `pip`:

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e .
cp .env.example .env               # fill in OPENAI_API_KEY
```

## Running an episode

```bash
cd episodes/01-loop
python agent.py
```

Each episode is self-contained. The agent operates on `episodes/<ep>/sandbox/`, which is freshly copied from `episodes/<ep>/initial/` on every run (the reset is in the first 5 lines of every `agent.py`).

### Recording a run

`run.py` runs an episode as a fresh **run**: it creates a new folder `<cwd>/logs/<timestamp>/` (gitignored, never overwritten), runs the agent, moves the agent's `tool_calls.jsonl` into that folder, and prints a summary of the tool calls. Add `--capture` to also record the terminal output there.

```bash
cd episodes/01-loop
python ../../run.py                       # a run: collects tool_calls.jsonl into logs/<timestamp>/
python ../../run.py --capture             # also save the terminal (terminal.log + terminal.jsonl)
```

Run **any** episode through `run.py` from the `code/` root with `--cwd`.

Run (records `tool_calls.jsonl` only):

```bash
python run.py --cwd episodes/01-loop                 # Episode 1 — the loop
python run.py --cwd episodes/02-tools                # Episode 2 — tools + @tool
python run.py --cwd episodes/03-context              # Episode 3 — compaction + done
python run.py --cwd episodes/04-planning-reasoning   # Episode 4 — planning + think
python run.py --cwd episodes/05-skills               # Episode 5 — skills
python run.py --cwd episodes/06-orchestration        # Episode 6 — orchestration
```

Run **and capture the terminal** (also writes `terminal.log` + `terminal.jsonl`):

```bash
python run.py --capture --cwd episodes/01-loop                 # Episode 1 — the loop
python run.py --capture --cwd episodes/02-tools                # Episode 2 — tools + @tool
python run.py --capture --cwd episodes/03-context              # Episode 3 — compaction + done
python run.py --capture --cwd episodes/04-planning-reasoning   # Episode 4 — planning + think
python run.py --capture --cwd episodes/05-skills               # Episode 5 — skills
python run.py --capture --cwd episodes/06-orchestration        # Episode 6 — orchestration
```

Because each run gets its own folder, you can run the same task repeatedly and compare how the agent's path and tool-call count differ — that run-to-run variance is itself a topic the series returns to. The episodes stay self-contained: `python agent.py` still works on its own (it just overwrites `tool_calls.jsonl` each time); `run.py` is the harness around it and can run any episode.

`capture.py` is the underlying terminal recorder — one job: run a command and tee its output to a log dir. `run.py` uses it for `--capture`, and it works standalone on any command too, e.g. `python capture.py -- pytest -q`.

From Episode 2 onward the agent records its own **tool-call telemetry**: it writes the full ordered sequence of tool calls to `tool_calls.jsonl`. The agent doesn't print a summary itself — it just does its task; `run.py` renders the summary (above) from that file.

After a run, inspect what the agent did:

```bash
diff -r initial sandbox
```

## Episodes

- **01-loop** — the minimal agent loop with one `bash` tool
- **02-tools** — multiple primitives + `@tool` helper + skills
- **03-context** — rolling-summary compaction + done tool
- **04-planning-reasoning** — `write_plan` (structured plan in agent state) + `think` (in-the-moment reasoning scratchpad)
- **05-orchestration** — multi-agent + `delegate`

## Provider portability

The code uses the `openai` Python package against the **Chat Completions API**. The same code points at any OpenAI-compatible endpoint by setting `LLM_BASE_URL` / `LLM_AGENT_MODEL` in `.env` (the matching API key is selected automatically). Compatible providers include OpenAI, Groq, Together, Mistral, DeepSeek, Ollama, vLLM, and OpenRouter.

## Toy codebase

Every episode operates on `md2html`, a small Markdown-to-HTML CLI. See `../spec/md2html.md` in the parent workspace for the full spec.
