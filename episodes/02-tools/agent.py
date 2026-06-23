"""
Episode 2 — Tools

Adds general primitives (list_files, read, write, edit, grep) alongside bash,
plus a tiny @tool decorator that builds each tool's JSON-schema from its
signature.
The tools now live in tools.py; this file is just the agent loop — which is
identical to Ep 1 except for dispatching by tool name. Naive stop condition is
still in place; the done tool arrives in Ep 3.

See ../../README.md for context.
"""
import json
import os
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from tiktoken import get_encoding

import tools  # module ref so the loop can set tools.CURRENT_ROUND each turn
from tools import SANDBOX, TOOL_DEFS, TOOLS_BY_NAME, write_tool_telemetry

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# --- 1. Sandbox reset. SANDBOX is defined in tools.py (the tools are bound to
# it); the reset to a clean copy of initial/ is the agent's bootstrap.
INITIAL = Path("initial")
if SANDBOX.exists():
    shutil.rmtree(SANDBOX)
shutil.copytree(INITIAL, SANDBOX)

# --- 2. LLM client. The openai package targets any OpenAI-compatible endpoint;
# switch providers by changing LLM_BASE_URL / LLM_AGENT_MODEL in .env.
load_dotenv(Path("../../.env"))


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


# tiktoken encoder for the per-round tool-result token count (tools_out). Most of
# the context growth is tool results (a file read dwarfs the model's request), so
# we measure their real token size. cl100k_base is OpenAI's tokenizer; on Claude
# it's a close approximation — fine for a telemetry count.
_ENC = get_encoding("cl100k_base")


def _count_tokens(messages):
    """Real token count (tiktoken) of these messages' content — used to record
    each round's tool-result total (tools_out)."""
    return len(_ENC.encode("\n".join(str(m.get("content") or "") for m in messages)))


# --- 3. Usage telemetry: token counts per run -> metrics.json. The harness
# (run.py) renders the summary. (Tool-call telemetry lives in tools.py, next to
# the decorator that records it.)
def write_metrics():
    """Write this run's token usage to metrics.json. Recording only — the
    harness (run.py) reads this and renders the summary, so the agent stays
    minimal and all usage reporting lives in one place."""
    metrics = {
        "agents": [{
            "label": "agent",
            "iterations": iteration,
            "input_tokens": total_in,
            "output_tokens": total_out,
            "per_iter": per_iter,  # {model_in, model_out, tools, tools_out} per round
        }],
        "inputs": {"system": SYSTEM, "task": TASK},
        "config": {"MODEL": MODEL},
    }
    with open("metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)


# --- 4. The agent loop. Identical to Ep 1 except for the dispatch by tool name.
SYSTEM = (
    "You are a coding assistant operating inside a sandboxed working "
    "directory. Use the available tools to investigate, modify, and "
    "verify code. Ground claims in what you actually observe; don't "
    "guess. When the task is complete, stop calling tools and produce "
    "a clear answer."
)
# The task: write a README. This continues Ep 1's second task -- only now the
# agent has real file tools, so the file lands in a single write() call instead
# of the many shell-escaping workarounds the bash-only agent needed in Ep 1.
TASK = (
    "This project has no README. Explore the codebase in the current directory "
    "and write a README.md for it. Cover: what the project does, how to install "
    "and use it (including the CLI), its architecture, and how to run the tests. "
    "Base everything on what you actually find in the code; don't guess."
)

messages = [
    {"role": "system", "content": SYSTEM},
    {"role": "user", "content": TASK},
]
print(f"USER: {TASK}\n")

total_in = total_out = 0
iteration = 0
per_iter = []

while True:
    iteration += 1
    tools.CURRENT_ROUND = iteration   # tag tool calls with the round they happen in
    resp = client.chat.completions.create(
        model=MODEL, messages=messages, tools=TOOL_DEFS,
    )
    usage = resp.usage
    total_in += usage.prompt_tokens
    total_out += usage.completion_tokens
    per_iter.append({"model_in": usage.prompt_tokens, "model_out": usage.completion_tokens, "tools": 0, "tools_out": 0})

    msg = resp.choices[0].message
    per_iter[-1]["tools"] = len(msg.tool_calls or [])   # tool calls requested this round
    messages.append(msg.model_dump(exclude_none=True))

    if not msg.tool_calls:
        print(f"\n=== FINAL RESPONSE ===\n\n{msg.content or ''}")
        write_tool_telemetry()
        write_metrics()
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
            # Tool errors come back to the model as the tool result, not as an agent crash.
            # The model can self-correct on the next iteration.
            result = f"Error executing {tc.function.name}: {type(e).__name__}: {e}"
            print(f"  ! {result}")
        preview = result if len(result) < 2000 else result[:2000] + "...[truncated]"
        print(f"  {preview}\n")
        tool_msg = {"role": "tool", "tool_call_id": tc.id, "content": result}
        round_tool_msgs.append(tool_msg)
        messages.append(tool_msg)

    # Tool results are most of the context growth (a file read dwarfs the model's
    # request); record this round's tool-result tokens so the per-iter numbers add up.
    per_iter[-1]["tools_out"] = _count_tokens(round_tool_msgs)
