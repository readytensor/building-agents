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

The loop lives in run_agent() — a function you can import and call from your
own code (give it a task, get the final answer). main() owns everything that
touches the world: the sandbox reset, the clients, and the telemetry files.

See ../../README.md for context.
"""
import json
import os
import shutil
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

# Load .env at import — before the local imports below, because compaction.py
# reads its knobs (threshold, keep, summarizer model) from the environment at
# import time. This is the one side effect that can't wait for main().
load_dotenv(Path("../../.env"))

import tools as tools_module  # noqa: E402  aliased: run_agent's `tools` parameter takes the canonical name; the loop sets tools_module.CURRENT_ROUND each turn
from tools import SANDBOX, TOOLS, write_tool_telemetry  # noqa: E402
from compaction import COMPACTION_THRESHOLD, KEEP_LAST_ITERATIONS, compact, _count_tokens  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# The agent's working directory: a fresh copy of initial/, reset by main().
# SANDBOX itself is defined in tools.py — the tools are bound to it.
INITIAL = Path("initial")


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


# --- Loop safety cap to prevent an infinite loop. (Compaction knobs live in
# compaction.py.)
MAX_ITERATIONS = int(os.environ.get("MAX_ITERATIONS", 150))

# The system prompt lives in system_prompt.md next to this file: prompt text is
# configuration, not loop logic. Its core is shared verbatim by every episode.
SYSTEM = (Path(__file__).parent / "system_prompt.md").read_text(encoding="utf-8")
TASK = """I'm about to start adding inline tokens to the parser, and the
generic name `Node` for our AST type is going to get confusing. Can you
rename `Node` to `ASTNode` throughout the codebase? The change is purely
naming — semantics stay identical. All tests should pass after."""

# --- Usage telemetry: token counts per run, recorded by run_agent as it goes.
# The agent only RECORDS (to metrics.json); the harness (run.py) RENDERS the
# summary. Compaction tokens are recorded separately so the harness can show
# the agent-vs-compaction split. (Tool-call telemetry lives in tools.py.)
USAGE = {
    "iterations": 0,
    "input_tokens": 0,
    "output_tokens": 0,
    "compactions": 0,
    "compact_in": 0,
    "compact_out": 0,
    "per_iter": [],  # {model_in, model_out, tools, tools_out, middle, compacted} per round
}


def write_metrics(model: str, summarizer_model: str, system: str, task: str):
    """Write this run's token usage to metrics.json. Recording only — the
    harness (run.py) reads this and renders the summary."""
    metrics = {
        "agents": [{"label": "agent", **USAGE}],
        "inputs": {"system": system, "task": task},
        "config": {
            "MODEL": model,
            "SUMMARIZER_MODEL": summarizer_model,
            "COMPACTION_THRESHOLD": COMPACTION_THRESHOLD,
            "KEEP_LAST_ITERATIONS": KEEP_LAST_ITERATIONS,
            "MAX_ITERATIONS": MAX_ITERATIONS,
        },
    }
    with open("metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)


# --- The agent loop, as a function. The signature is the anatomy of an agent:
# a model, a system prompt, tools, and a task — plus this episode's addition,
# the summarizer that compaction runs on.
def run_agent(client, model: str, system: str, tools: list,
              summarizer_client, summarizer_model: str, task: str):
    """Run the agent loop on `task` until the model stops requesting tool calls
    (the natural stop); return its final message. Returns None if the loop hits
    MAX_ITERATIONS first. Records token usage into USAGE along the way (tool
    calls record themselves in tools.py)."""
    tools_by_name = {t.__name__: t for t in tools}
    tool_defs = [t.tool_definition for t in tools]
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": task},
    ]
    iteration = 0

    while iteration < MAX_ITERATIONS:
        iteration += 1
        tools_module.CURRENT_ROUND = iteration   # tag tool calls with the round they happen in
        resp = client.chat.completions.create(
            model=model, messages=messages, tools=tool_defs,
        )
        u = resp.usage
        USAGE["iterations"] = iteration
        USAGE["input_tokens"] += u.prompt_tokens
        USAGE["output_tokens"] += u.completion_tokens
        USAGE["per_iter"].append({"model_in": u.prompt_tokens, "model_out": u.completion_tokens, "tools": 0, "tools_out": 0, "middle": 0, "compacted": False})

        msg = resp.choices[0].message
        USAGE["per_iter"][-1]["tools"] = len(msg.tool_calls or [])   # tool calls requested this round
        messages.append(msg.model_dump(exclude_none=True))

        if not msg.tool_calls:
            # Natural stop: no tool calls means the model considers the task done.
            return msg.content or ""

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
        USAGE["per_iter"][-1]["tools_out"] = _count_tokens(round_tool_msgs)

        # Compaction: compact() summarizes the older middle once the MIDDLE's own
        # token count crosses the threshold, and no-ops otherwise — so it's safe to
        # call every turn; it only summarizes when there's enough stale middle to be
        # worth it (and with KEEP small, the fire drops the input hard).
        before = len(messages)
        messages, did, ci, co, middle_tok = compact(messages, summarizer_client, summarizer_model)
        USAGE["per_iter"][-1]["middle"] = middle_tok   # compactable-middle size this turn (the sawtooth metric)
        if did:
            USAGE["compactions"] += 1
            USAGE["per_iter"][-1]["compacted"] = True   # the middle crossed the threshold this iteration
            USAGE["compact_in"] += ci
            USAGE["compact_out"] += co
            print(f"  [COMPACTION FIRED — {before} messages → {len(messages)}, summarizer in={ci} out={co}]\n")

    return None   # iteration cap reached without a natural stop


# --- Setup and run. Everything with side effects lives here (except the .env
# load above), so importing this module to reuse run_agent touches nothing.
def main():
    # Sandbox reset: every run starts from a clean copy of initial/.
    if SANDBOX.exists():
        shutil.rmtree(SANDBOX)
    shutil.copytree(INITIAL, SANDBOX)

    # LLM client. The openai package targets any OpenAI-compatible endpoint;
    # switch providers by changing LLM_BASE_URL / LLM_AGENT_MODEL in .env.
    base_url = os.environ.get("LLM_BASE_URL") or ""
    model = os.environ.get("LLM_AGENT_MODEL", "gpt-5-mini")
    client = OpenAI(api_key=api_key_for(base_url), base_url=base_url or None)

    # Compaction summarizes on its own model — and, if pointed at a different
    # provider, its own endpoint. Both default to the agent's, so leaving the
    # LLM_SUMMARIZER_* vars unset simply reuses the agent's client.
    summarizer_base_url = os.environ.get("LLM_SUMMARIZER_BASE_URL") or base_url
    summarizer_model = os.environ.get("LLM_SUMMARIZER_MODEL") or model
    summarizer_client = (
        client if summarizer_base_url == base_url
        else OpenAI(api_key=api_key_for(summarizer_base_url), base_url=summarizer_base_url or None)
    )

    print(f"USER: {TASK}\n")
    final = run_agent(client, model, SYSTEM, TOOLS, summarizer_client, summarizer_model, TASK)
    if final is None:
        print(f"\n=== MAX_ITERATIONS REACHED ({MAX_ITERATIONS}) — aborting ===")
    else:
        print(f"\n=== FINAL RESPONSE ===\n\n{final}")
    write_tool_telemetry()
    write_metrics(model, summarizer_model, SYSTEM, TASK)


if __name__ == "__main__":
    main()
