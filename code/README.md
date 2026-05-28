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

### Capturing a run

To save everything the agent prints — handy for reviewing or debugging a run afterwards — launch it through `capture.py` instead of running `agent.py` directly:

```bash
cd episodes/01-loop
python ../../capture.py                  # defaults to: python -u agent.py
```

It mirrors the agent's output to your terminal live **and** writes each run to its own folder `<cwd>/logs/<timestamp>/` (gitignored), so runs never overwrite each other. Each folder holds `terminal.log` (human-readable, each line prefixed with elapsed time, e.g. `[+ 12.34s]`), `terminal.jsonl` (`{"t", "text"}` records for later inspection), and the run's `tool_calls.jsonl` (collected from the agent — see below). Works the same on every episode and every platform.

`capture.py` runs any command, not just `agent.py` — e.g. `python capture.py -- pytest -q` or `python capture.py --cwd episodes/03-context`.

Separately, from Episode 2 onward the agent records its own **tool-call telemetry**: at the end of a run it prints a summary (how many tools it called, in what order) and writes the full sequence to `tool_calls.jsonl`. When run through `capture.py`, that file is moved into the run folder, so each run's path is preserved. The number and order of calls varies run to run — that variance is itself a topic the series returns to.

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

The code uses the `openai` Python package against the **Chat Completions API**. The same code points at any OpenAI-compatible endpoint by overriding `OPENAI_BASE_URL` in `.env`. Compatible providers include OpenAI, Groq, Together, Mistral, DeepSeek, Ollama, vLLM, and OpenRouter.

## Toy codebase

Every episode operates on `md2html`, a small Markdown-to-HTML CLI. See `../spec/md2html.md` in the parent workspace for the full spec.
