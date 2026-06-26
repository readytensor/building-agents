"""
Episode 3 — Compaction

Adds one thing to Ep 2's agent: rolling-summary compaction. When the compactable
*middle* of the message history grows past COMPACTION_THRESHOLD, that middle is
summarized and replaced with one summary message — so a long-running task doesn't
keep re-paying for the full transcript on every turn.

The action space is unchanged from Ep 2 (same tools.py). Completion is still the
natural stop: the loop ends when the model emits no tool calls — its trained
instinct that the task is done. (Rigorous, externally-verified completion —
running pre-written tests and only stopping when they pass — arrives later, as
the verification skill.)

This file is just the agent loop. The compaction mechanism gets its own
compaction.py; both it and tools.py import one-way (`agent → tools`,
`agent → compaction`) — agent.py owns the LLM client and passes it into
compact().

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
# knobs (threshold, keep, summarizer model) from the environment at import time,
# so the .env values have to be present first.
load_dotenv(Path("../../.env"))

import tools  # noqa: E402  module ref so the loop can set tools.CURRENT_ROUND each turn
from tools import SANDBOX, TOOL_DEFS, TOOLS_BY_NAME, write_tool_telemetry  # noqa: E402
from compaction import COMPACTION_THRESHOLD, KEEP_LAST_ITERATIONS, compact, _count_tokens  # noqa: E402

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
MAX_ITERATIONS = int(os.environ.get("EP3_MAX_ITER", 150))


# --- 3. Usage telemetry: token counts per run -> metrics.json. The harness
# (run.py) renders the summary. (Tool-call telemetry lives in tools.py.)
def write_metrics():
    """Write this run's token usage to metrics.json. Recording only — the
    harness (run.py) reads this and renders the summary. Compaction tokens are
    recorded separately so the harness can show the agent-vs-compaction split."""
    metrics = {
        "agents": [{
            "label": "agent",
            "iterations": iteration,
            "input_tokens": total_in,
            "output_tokens": total_out,
            "compactions": compactions_fired,
            "compact_in": compact_in,
            "compact_out": compact_out,
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


# --- 4. The agent loop.
SYSTEM = (
    "You are a coding assistant operating inside a sandboxed working "
    "directory. Use the available tools to investigate, modify, and "
    "verify code. Ground claims in what you actually observe; don't "
    "guess. When the task is complete, stop calling tools and produce "
    "a clear summary of what you did."
)
TASK = """I'm about to start adding inline tokens to the parser, and the
generic name `Node` for our AST type is going to get confusing. Can you
rename `Node` to `ASTNode` throughout the codebase? The change is purely
naming — semantics stay identical. All tests should pass after."""

messages = [
    {"role": "system", "content": SYSTEM},
    {"role": "user", "content": TASK},
]
print(f"USER: {TASK}\n")

total_in = total_out = 0
compact_in = compact_out = 0
iteration = 0
compactions_fired = 0
per_iter = []

while iteration < MAX_ITERATIONS:
    iteration += 1
    tools.CURRENT_ROUND = iteration   # tag tool calls with the round they happen in
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
