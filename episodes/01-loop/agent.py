"""
Episode 1 — The Loop

Minimal agent: a while-loop calling a single `bash` tool until the model stops
requesting tool calls. Naive stop condition. 

See ../../README.md for context.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from tiktoken import get_encoding

# Windows: make sure stdout can render UTF-8 (LLM outputs often contain → ✓ etc.)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# --- 1. Sandbox reset: every run starts from a clean copy of initial/.
INITIAL = Path("initial")
SANDBOX = Path("sandbox")
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

# --- 3. The one tool: bash, bounded to the sandbox directory.
def bash(command: str) -> str:
    """Execute a shell command inside the sandbox and return its output.

    check=False is deliberate: command failures (non-zero exit) come back to
    the LLM as tool output so the model can adapt — e.g., 'ls' fails on
    Windows cmd, the LLM sees the error and pivots to 'dir'. Crashing the
    agent on non-zero exit would defeat that.

    shell=True is also deliberate — this IS the bash tool. The security
    model is the sandbox boundary (cwd bounded to a fresh copy of initial/),
    not the subprocess argument shape.
    """
    result = subprocess.run(
        command, shell=True, capture_output=True, text=True,
        cwd=SANDBOX, timeout=30,
        encoding="utf-8", errors="replace",
        check=False,
    )
    output = (result.stdout + result.stderr).strip()
    return output or "(no output)"

BASH_TOOL = {
    "type": "function",
    "function": {
        "name": "bash",
        "description": "Execute a shell command in the working directory and return its output.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "The shell command to run."},
            },
            "required": ["command"],
        },
    },
}

# --- 4. The agent loop.
SYSTEM = (
    "You are a coding assistant operating inside a sandboxed working "
    "directory. Use the available tools to investigate, modify, and "
    "verify code. Ground claims in what you actually observe; don't "
    "guess. When the task is complete, stop calling tools and produce "
    "a clear answer."
)
# Two tasks for the same agent. The agent is identical; only this string changes.
# The first asks it to summarize the project; the second asks it to write a README.
# To try the second, comment out the first TASK and uncomment the second.
TASK = (  # summarize the project
    "This project has no README. Explore the codebase in the current directory "
    "and tell me what it does: its purpose, how to use it, and how it's "
    "structured, in 100-150 words. Base it on what you actually find in the "
    "code; don't guess."
)
# TASK = (  # write the README
#     "This project has no README. Explore the codebase in the current directory "
#     "and write a README.md for it. Cover: what the project does, how to install "
#     "and use it (including the CLI), its architecture, and how to run the tests. "
#     "Base everything on what you actually find in the code; don't guess."
# )

# --- Tool-call telemetry: record every tool the agent invokes, in order, so
# we can see the path it took and how many calls it made (this varies run to
# run). Summarized and written to tool_calls.jsonl at the end of the run.
TOOL_CALLS = []  # list of {"tool": name, "args": {...}} in call order

def write_tool_telemetry():
    """Write the tool calls made this run to tool_calls.jsonl, one JSON object
    per line in call order. Recording only — rendering a summary is left to
    whatever reads the file."""
    with open("tool_calls.jsonl", "w", encoding="utf-8") as f:
        for call in TOOL_CALLS:
            f.write(json.dumps(call) + "\n")

# tiktoken encoder for the per-round tool-result token count (tools_out). Most of
# the context growth is tool results (a file read dwarfs the model's request), so
# we measure their real token size. cl100k_base is OpenAI's tokenizer; on Claude
# it's a close approximation — fine for a telemetry count.
_ENC = get_encoding("cl100k_base")


def _count_tokens(messages):
    """Real token count (tiktoken) of these messages' content — used to record
    each round's tool-result total (tools_out)."""
    return len(_ENC.encode("\n".join(str(m.get("content") or "") for m in messages)))


# --- Usage telemetry: record token usage per run, the same way as tool calls.
# The agent only RECORDS (to metrics.json); the harness (run.py) RENDERS the
# summary. Keeping reporting out of the agent keeps it minimal.
def write_metrics():
    """Write this run's token usage to metrics.json. Recording only — run.py
    reads this and prints the summary."""
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
    resp = client.chat.completions.create(
        model=MODEL, messages=messages, tools=[BASH_TOOL],
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
        args = json.loads(tc.function.arguments)
        TOOL_CALLS.append({"round": iteration, "tool": tc.function.name, "args": args})
        print(f"> bash({args['command']!r})")
        result = bash(**args)
        if len(result) < 5000:
            preview = result
        else:
            preview = result[:5000] + "...[truncated]"
        print(f"  {preview}\n")
        tool_msg = {"role": "tool", "tool_call_id": tc.id, "content": result}
        round_tool_msgs.append(tool_msg)
        messages.append(tool_msg)

    # Tool results are most of the context growth (a file read dwarfs the model's
    # request); record this round's tool-result tokens so the per-iter numbers add up.
    per_iter[-1]["tools_out"] = _count_tokens(round_tool_msgs)
