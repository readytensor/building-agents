"""
Episode 4 — Working Memory

Gives the agent durable, self-maintained state that survives compaction.

The mechanism is a *dynamic system prompt*: each iteration the loop rebuilds the
system message as [stable base + current plan]. Because the plan lives in agent
state (not message history) it survives compaction untouched, and because it
rides in the system prompt the message prefix stays stable when the plan is
unchanged. write_plan (see planning.py) is the worked instance of that durable
slot — a structured plan the agent writes and updates as it works; the same
mechanism is what Ep 5 builds on to inject loaded-skill bodies.

Everything else is Ep 3 unchanged: the action space (tools.py), rolling-summary
compaction (compaction.py), the sandbox reset, and the natural stop — the loop
ends when the model emits no tool calls. (No self-assessed done tool; rigorous,
externally-verified completion arrives later, as the verification skill.)

This file is just the agent loop. It owns the LLM client and passes it into
compact(); imports are one-way (`agent → tools`, `agent → compaction`,
`agent → planning`).

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

import tools  # noqa: E402  module ref so the loop can set tools.CURRENT_ROUND each turn
from tools import SANDBOX, TOOLS as BASE_TOOLS, write_tool_telemetry  # noqa: E402
from compaction import COMPACTION_THRESHOLD, KEEP_LAST_ITERATIONS, compact, _count_tokens  # noqa: E402
from planning import write_plan, system_with_plan  # noqa: E402

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
MAX_ITERATIONS = int(os.environ.get("MAX_ITERATIONS", 150))

# --- 3. Tool registry: Ep 3's six file primitives plus Ep 4's new
# tool, write_plan. (Tool-call telemetry lives in tools.py.)
TOOLS = BASE_TOOLS + [write_plan]
TOOLS_BY_NAME = {t.__name__: t for t in TOOLS}
TOOL_DEFS = [t.tool_definition for t in TOOLS]


# --- 4. Usage telemetry: token counts per run -> metrics.json. The harness
# (run.py) renders the summary. (Tool-call telemetry lives in tools.py.)
def write_metrics():
    """Write this run's token usage to metrics.json. Recording only — the
    harness (run.py) reads this and renders the summary. Compaction tokens are
    recorded separately, as is the write_plan count, so the harness can show the
    agent-vs-compaction split and how often the new tool fired."""
    metrics = {
        "agents": [{
            "label": "agent",
            "iterations": iteration,
            "input_tokens": total_in,
            "output_tokens": total_out,
            "compactions": compactions_fired,
            "compact_in": compact_in,
            "compact_out": compact_out,
            # "reasoning" is the shared metrics key across Eps 4-6 + run.py —
            # a stable grouping for write_plan's call count.
            "reasoning": {"write_plan": plan_writes},
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
SYSTEM = (
    "You are a coding assistant operating inside a sandboxed working "
    "directory. Use the available tools to investigate, modify, and "
    "verify code. Ground claims in what you actually observe; don't "
    "guess. Before you produce a final response, if a plan exists, update "
    "it so completed work is marked completed and any remaining work is "
    "accurately reflected. When the task is complete, stop calling tools "
    "and produce a clear summary of what you did."
)
TASK = """I want to add support for reference-style links to our markdown
library. They look like this:

    Here is a [link][myref] in text.

    [myref]: https://example.com "Optional title"

The link definitions (the `[id]: url "title"` lines) get collected from
the document, and inline `[text][id]` references resolve to <a> elements
using those URLs. The definition lines themselves should NOT appear in
the rendered output.

This touches a few parts of the pipeline, so plan the work first and
track your progress against it as you go.

I've added a test fixture at tests/fixtures/reference_style_links.md and
tests/fixtures/reference_style_links.html showing the expected behavior;
it currently fails. Make it pass, and make sure the existing tests still
pass too."""

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
per_iter = []

while iteration < MAX_ITERATIONS:
    iteration += 1
    tools.CURRENT_ROUND = iteration   # tag tool calls with the round they happen in

    # Dynamic system prompt: rebuild messages[0] from the stable base plus the
    # current plan. The plan lives in agent state (planning.CURRENT_PLAN), so
    # this re-injects it fresh each turn without ever touching message history.
    messages[0] = {"role": "system", "content": system_with_plan(SYSTEM)}

    resp = client.chat.completions.create(
        model=MODEL, messages=messages, tools=TOOL_DEFS,
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
            fn = TOOLS_BY_NAME[tc.function.name]
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
