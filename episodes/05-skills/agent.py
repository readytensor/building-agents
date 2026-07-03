"""
Episode 5 — Skills

Adds a skills system to Ep 4's agent: lazy-loadable bundles of procedural
knowledge + tools, modeled on Claude Code's skill abstraction (a SKILL.md
per directory with YAML frontmatter + a body of procedural instructions).

What Ep 5 adds (all in skills.py):
  - list_skills() — discover what skills exist (name + description).
  - load_skill(name) — load a skill's body into the system prompt and
    register the tools it provides for the rest of the run.
  - skill-provided tools that only appear once their skill loads:
    web_search + fetch_url (research), lint + coverage (verification).

The system-prompt injection reuses Ep 4's dynamic-system-prompt mechanism:
each turn the loop rebuilds messages[0] as base + plan + loaded-skill bodies
(see skills.system_with_skills wrapped around planning.system_with_plan).
Because skills live in agent state, not message history, they survive
compaction and keep the message prefix stable.

Everything else is inherited: the action space (tools.py), rolling-summary
compaction (compaction.py), the plan (planning.py), the sandbox reset,
and the natural stop — the loop ends when the model emits no tool calls.
(No self-assessed done tool; rigorous, externally-verified completion is the
job of the `verification` skill, which runs the tests before the agent stops.)

This file is just the agent loop. It owns the LLM client and passes it into
compact(); imports are one-way (agent → tools / compaction / planning / skills).

See ../../README.md for context.
"""
import json
import os
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

# Load .env before importing the local modules below — compaction.py reads its
# knobs (threshold, keep) from the environment at import time, so the .env
# values have to be present first.
load_dotenv(Path("../../.env"))

import skills  # noqa: E402  module ref so the loop can read skills.LOADED_TOOLS each turn
import tools  # noqa: E402  module ref so the loop can set tools.CURRENT_ROUND each turn
from tools import SANDBOX, TOOLS as FILE_TOOLS, write_tool_telemetry  # noqa: E402
from compaction import COMPACTION_THRESHOLD, KEEP_LAST_ITERATIONS, compact, _count_tokens  # noqa: E402
from planning import write_plan, system_with_plan  # noqa: E402
from skills import list_skills, load_skill, system_with_skills  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# --- 1. Sandbox reset. SANDBOX is defined in tools.py (the tools are bound to
# it); the reset to a clean copy of initial/ is the agent's bootstrap.
INITIAL = Path("initial")
if SANDBOX.exists():
    shutil.rmtree(SANDBOX)
shutil.copytree(INITIAL, SANDBOX)

# --- 2. LLM client. The openai package targets any OpenAI-compatible endpoint;
# switch providers by changing LLM_BASE_URL / LLM_AGENT_MODEL in .env.
def api_key_for(base_url: str):
    """Return the API key for the provider in `base_url`, read from the
    environment — so switching providers means changing only LLM_BASE_URL, never
    moving keys around. Anything OpenAI-compatible (Together, DeepSeek,
    OpenRouter, …) falls through to OPENAI_API_KEY."""
    by_provider = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
        "groq": "GROQ_API_KEY",
        "googleapis": "GOOGLE_API_KEY",
        "manus": "MANUS_API_KEY",
    }
    for fragment, key_var in by_provider.items():
        if fragment in base_url:
            return os.environ.get(key_var)
    return os.environ.get("OPENAI_API_KEY")


BASE_URL = os.environ.get("LLM_BASE_URL") or ""
MODEL = os.environ.get("LLM_AGENT_MODEL", "gpt-5-mini")
client = OpenAI(api_key=api_key_for(BASE_URL), base_url=BASE_URL or None)

# Compaction summarizes on its own model — and, if pointed at a different
# provider, its own endpoint. Both default to the agent's, so leaving the
# LLM_SUMMARIZER_* vars unset simply reuses the agent's client.
SUMMARIZER_BASE_URL = os.environ.get("LLM_SUMMARIZER_BASE_URL") or BASE_URL
SUMMARIZER_MODEL = os.environ.get("LLM_SUMMARIZER_MODEL") or MODEL
summarizer_client = (
    client if SUMMARIZER_BASE_URL == BASE_URL
    else OpenAI(api_key=api_key_for(SUMMARIZER_BASE_URL), base_url=SUMMARIZER_BASE_URL or None)
)

# --- Loop safety cap to prevent an infinite loop. (Compaction knobs live in
# compaction.py.)
MAX_ITERATIONS = int(os.environ.get("MAX_ITERATIONS", 200))

# --- 3. Tool registry. The base tools are always available: Ep 4's seven
# (six file primitives + write_plan) plus Ep 5's two skill tools (list_skills,
# load_skill). Skill-provided tools (web_search, lint, …) are NOT here —
# load_skill adds them to skills.LOADED_TOOLS, and the loop merges that in each
# turn, so a tool the agent unlocks mid-run becomes callable.
BASE_TOOLS = FILE_TOOLS + [write_plan, list_skills, load_skill]
BASE_TOOLS_BY_NAME = {t.__name__: t for t in BASE_TOOLS}


def live_tools():
    """The tools available THIS turn: the always-on base tools plus any tools
    unlocked by skills loaded so far. Returns (tools_by_name, tool_defs)."""
    tools_by_name = {**BASE_TOOLS_BY_NAME, **skills.LOADED_TOOLS}
    tool_defs = [fn.tool_definition for fn in tools_by_name.values()]
    return tools_by_name, tool_defs


# --- 4. Usage telemetry: token counts per run -> metrics.json. The harness
# (run.py) renders the summary. (Tool-call telemetry lives in tools.py.)
def write_metrics():
    """Write this run's token usage to metrics.json. Recording only — the
    harness (run.py) reads this and renders the summary. Compaction tokens,
    the write_plan count, and the skill-use counts are all recorded separately
    so the harness can show each section."""
    metrics = {
        "agents": [{
            "label": "agent",
            "iterations": iteration,
            "input_tokens": total_in,
            "output_tokens": total_out,
            "compactions": compactions_fired,
            "compact_in": compact_in,
            "compact_out": compact_out,
            "reasoning": {"write_plan": plan_writes},
            "skills": {
                "list_skills": list_skills_calls,
                "load_skill": load_skill_calls,
                "loaded": loaded_skill_names,
            },
            "per_iter": per_iter,  # {model_in, model_out, tools, tools_out, middle, compacted} per round
        }],
        "inputs": {"system": SYSTEM, "task": TASK},
        "config": {
            "MODEL": MODEL,
            "SUMMARIZER_MODEL": SUMMARIZER_MODEL,
            "COMPACTION_THRESHOLD": COMPACTION_THRESHOLD,
            "KEEP_LAST_ITERATIONS": KEEP_LAST_ITERATIONS,
            "MAX_ITERATIONS": MAX_ITERATIONS,
        },
    }
    with open("metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)


# --- 5. The agent loop.
SYSTEM = """You are a coding assistant operating inside a working copy of a \
code repository. Use the available tools to investigate, modify, and verify code.

## Skills
- Call list_skills() when you start a task, and load_skill(name) for any skill \
whose description matches the work.
- If you need a capability or tool you don't currently have, check list_skills \
first (a skill may provide it) rather than assuming you can't do the task.

## Working plan
- If a plan exists, keep it current: before you produce a final response, \
update it so completed work is marked completed and any remaining work is \
accurately reflected.

## Verification: required whenever you change code
- If your task involved modifying the codebase, you MUST run the project's own \
test suite with its own runner before your final answer. Scope it to the \
relevant test files if the full suite is slow.
- If your task did NOT change code (exploring, answering questions, writing \
documentation), do not run the test suite unless the task asks for it.
- Tests or reproduction scripts you write yourself are fine to use while \
working, but they are not a substitute for the project's existing suite: the \
suite catches regressions you didn't think of.
- The project's existing tests are a regression contract: do NOT modify or \
delete them. Adding new tests is fine and encouraged. If an existing test \
fails after your change, that is evidence your change altered existing \
behavior; fix your change, not the test.
- If tests fail, fix the cause and run them again. Do not stop while tests you \
could have run remain unrun.
- If the environment truly prevents running the tests, say so explicitly in \
your final summary.

## Final change hygiene
- Prefer the smallest edit that fixes the issue over rewriting working code.
- Delete any scratch files or notes you created, so only the intended change remains.

Ground claims in what you actually observe; don't guess. When the task is \
complete, stop calling tools and produce a clear summary of what you did or found."""

TASK = """I want to add support for GitHub-flavored alerts to md2html.
They look like this:

    > [!NOTE]
    > Useful information that users should know.

    > [!WARNING]
    > Urgent info that needs immediate attention.

**IMPORTANT — read carefully:**
The test fixture at tests/fixtures/github_alerts.html may be WRONG —
I wrote it from memory and I'm not confident about the exact class
names. GitHub's actual docs are the ground truth, NOT the fixture.

You MUST use web_search to look up GitHub's latest docs FIRST to
confirm the exact class names and HTML structure. If your
implementation matches the fixture but doesn't match what GitHub
actually emits, the work is incorrect even if pytest passes. If the
docs contradict the fixture, fix the fixture to match the docs.

THEN implement the extension as a new file under md2html/extensions/.
Keep your diff minimal — don't refactor unrelated parts of the
codebase. All existing tests must still pass."""

messages = [
    {"role": "system", "content": SYSTEM},
    {"role": "user", "content": TASK},
]
print(f"USER: {TASK}\n")

total_in = total_out = 0
compact_in = compact_out = 0
iteration = 0
compactions_fired = 0
plan_writes = 0
list_skills_calls = 0
load_skill_calls = 0
loaded_skill_names: list[str] = []
per_iter = []

while iteration < MAX_ITERATIONS:
    iteration += 1
    tools.CURRENT_ROUND = iteration   # tag tool calls with the round they happen in

    # Dynamic system prompt: rebuild messages[0] from the stable base plus the
    # current plan plus any loaded-skill bodies. All of these live in agent
    # state (not message history), so this re-injects them fresh each turn
    # without ever touching the transcript.
    messages[0] = {"role": "system", "content": system_with_skills(system_with_plan(SYSTEM))}

    # The tools list grows as skills load, so rebuild it each turn too.
    tools_by_name, tool_defs = live_tools()

    resp = client.chat.completions.create(
        model=MODEL, messages=messages, tools=tool_defs,
    )
    u = resp.usage
    total_in += u.prompt_tokens
    total_out += u.completion_tokens
    per_iter.append({"model_in": u.prompt_tokens, "model_out": u.completion_tokens, "tools": 0, "tools_out": 0, "middle": 0, "compacted": False})

    msg = resp.choices[0].message
    per_iter[-1]["tools"] = len(msg.tool_calls or [])   # tool calls requested this round
    messages.append(msg.model_dump(exclude_none=True))

    if not msg.tool_calls:
        # Natural stop: no tool calls means the model considers the task done.
        print(f"\n=== FINAL RESPONSE ===\n\n{msg.content or ''}")
        break

    round_tool_msgs = []
    for tc in msg.tool_calls:
        try:
            fn = tools_by_name[tc.function.name]
            args = json.loads(tc.function.arguments)
            parts = []
            for k, v in args.items():
                if len(repr(v)) < 60:
                    parts.append(f"{k}={v!r}")
                else:
                    parts.append(f"{k}=<{len(str(v))} chars>")
            arg_preview = ", ".join(parts)
            print(f"> {tc.function.name}({arg_preview})")
            result = fn(**args)
            if tc.function.name == "write_plan":
                plan_writes += 1
            elif tc.function.name == "list_skills":
                list_skills_calls += 1
            elif tc.function.name == "load_skill":
                load_skill_calls += 1
                # Record which skill actually loaded (the name is in the args).
                sname = args.get("name")
                if sname and sname in skills.LOADED_SKILLS and sname not in loaded_skill_names:
                    loaded_skill_names.append(sname)
        except (TypeError, KeyError, json.JSONDecodeError, ValueError) as e:
            # Bad tool call (missing args, unknown tool, etc.) — feed the error
            # back to the model so it can self-correct rather than crashing.
            result = f"Error executing {tc.function.name}: {type(e).__name__}: {e}"
            print(f"  ! {result}")
        preview = result if len(result) < 5000 else result[:5000] + "...[truncated]"
        print(f"  {preview}\n")
        tool_msg = {"role": "tool", "tool_call_id": tc.id, "content": result}
        round_tool_msgs.append(tool_msg)
        messages.append(tool_msg)

    # Tool results are most of the context growth: the model only *requests* a tool
    # (small `out`), but the result it hands back can be huge (a file read). Record
    # this round's tool-result tokens so the per-iter numbers actually add up.
    per_iter[-1]["tools_out"] = _count_tokens(round_tool_msgs)

    # Compaction: compact() summarizes the older middle once the MIDDLE's own
    # token count crosses the threshold, and no-ops otherwise — so it's safe to
    # call every turn; it only summarizes when there's enough stale middle to be
    # worth it (and with KEEP small, the fire drops the input hard).
    before = len(messages)
    messages, did, ci, co, middle_tok = compact(messages, summarizer_client, SUMMARIZER_MODEL)
    per_iter[-1]["middle"] = middle_tok   # compactable-middle size this turn (the sawtooth metric)
    if did:
        compactions_fired += 1
        per_iter[-1]["compacted"] = True   # the middle crossed the threshold this iteration
        compact_in += ci
        compact_out += co
        print(f"  [COMPACTION FIRED — {before} messages → {len(messages)}, summarizer in={ci} out={co}]\n")
else:
    print(f"\n=== MAX_ITERATIONS REACHED ({MAX_ITERATIONS}) — aborting ===")

write_tool_telemetry()
write_metrics()
