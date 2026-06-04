# AGENTS.md

Guidance for AI coding agents (and curious humans) working in this repository.

This is the companion code for the **"Agents from First Principles"** video series by Clyep. It builds one coding agent from scratch across six episodes: a plain `while` loop with a single tool in Episode 1, all the way to multi-agent orchestration in Episode 6, using a small Markdown-to-HTML CLI called `md2html` as the example project to work on. No frameworks: just Python and a model API.

For the full series narrative, the episode table, and setup/quickstart, read [`README.md`](./README.md). This file covers how to *work* in the repo, not what the series teaches.

## Finding your way around

```
building-agents/
├── episodes/
│   ├── 01-loop/
│   │   ├── agent.py      # the episode's agent: start here
│   │   ├── initial/      # pristine starting copy of the md2html project
│   │   └── sandbox/      # where the agent works (recreated every run)
│   ├── 02-tools/  03-context/  04-planning-thinking/  05-skills/  06-orchestration/
├── run.py                # optional harness to record a run
├── capture.py            # terminal recorder used by run.py --capture
└── requirements.txt
```

Each episode is **self-contained**: `cd` into it and run `python agent.py`. Episodes build on each other conceptually, but each one is a complete, standalone program: there is no shared library and no branch switching. The interesting comparison is the diff:

```bash
diff episodes/01-loop/agent.py episodes/02-tools/agent.py   # what one idea added
```

## Ground rules when working here

- **Never modify `initial/`.** It is the pristine template the agent starts from. Every `agent.py` begins by wiping `sandbox/` and copying `initial/` into it, so each run starts from an identical clean state. If you change `initial/`, you change the experiment.
- **`sandbox/` is ephemeral.** It is recreated on every run and is gitignored. Don't keep anything there you care about, and don't be surprised when it resets.
- **Stay inside one episode.** A change for Episode 3 belongs in `episodes/03-context/`. Don't edit one episode's files to fix another, and don't let one episode's `agent.py` reach into another's directory.
- **The diff between episodes is the lesson.** When you add or change something, keep the *delta* from the previous episode small and legible: that delta is the teaching point, not just the end state.

## Verify your work

`md2html` ships with a pytest suite. Use it, because that's the whole point of working against a tested codebase.

```bash
cd episodes/02-tools/sandbox && python -m pytest -q
```

**"Done" means the tests pass, not that the agent (or you) said so.** Confirm with command output before claiming a change works. Several episodes are built around exactly this discipline: verifying with tests rather than trusting a self-assessment.

## Code conventions

This is a **teaching repository**. The code is the artifact students learn from, so optimize for being read, not for being clever.

- **Write code that's easy to follow.** Clear names, obvious control flow, short functions. Not unnecessarily verbose (but not production-dense code packed for performance or generality either). If a student has to pause to decode a line, rewrite it.
- **One idea per episode.** Each episode adds exactly one concept on top of the last. Keep changes minimal and focused; resist adding scaffolding or features the episode doesn't need.
- **No frameworks.** The series builds agents from primitives on purpose. Reach for the standard library and the model API, not an agent framework.
- **Provider-portable LLM calls.** The code uses the `openai` Python package against the **Chat Completions API** so it runs against any OpenAI-compatible endpoint (set `LLM_BASE_URL` / `LLM_AGENT_MODEL` in `.env`). Avoid provider-specific features: keep it portable.

## Out of scope

This series is about the architectural core of how agents work: the loop, tools, context management, planning, skills, and multi-agent topology. Production ops, durable execution, full guardrails, framework reviews, and model training/RL are each their own topic and deliberately left out. Don't pull them in.
