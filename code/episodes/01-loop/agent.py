"""
Episode 1 — The Loop

Minimal agent: a while-loop calling a single `bash` tool until the model stops
requesting tool calls. Naive stop condition. ~80 lines.

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

# Windows: make sure stdout can render UTF-8 (LLM outputs often contain → ✓ etc.)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# --- 1. Sandbox reset: every run starts from a clean copy of initial/.
INITIAL = Path("initial")
SANDBOX = Path("sandbox")
if SANDBOX.exists():
    shutil.rmtree(SANDBOX)
shutil.copytree(INITIAL, SANDBOX)

# --- 2. LLM client. The openai package targets any OpenAI-compatible endpoint.
load_dotenv(Path("../../.env"))
BASE_URL = os.environ.get("OPENAI_BASE_URL") or ""
if "anthropic" in BASE_URL:
    API_KEY = os.environ.get("ANTHROPIC_API_KEY")
else:
    API_KEY = os.environ.get("OPENAI_API_KEY")
MODEL = os.environ.get("OPENAI_MODEL", "gpt-5-mini")
client = OpenAI(api_key=API_KEY, base_url=BASE_URL or None)

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
TASK = "Explore the codebase in the current directory and tell me what it does."

# --- Tool-call telemetry: record every tool the agent invokes, in order, so
# we can see the path it took and how many calls it made (this varies run to
# run). Summarized and written to tool_calls.jsonl at the end of the run.
TOOL_CALLS = []  # list of {"tool": name, "args": {...}} in call order

def write_tool_telemetry():
    """Print a summary of the tool calls made this run, and write the full
    ordered sequence to tool_calls.jsonl. The number of calls and their order
    vary from run to run."""
    counts = {}
    for call in TOOL_CALLS:
        counts[call["tool"]] = counts.get(call["tool"], 0) + 1
    breakdown = ", ".join(f"{name}×{n}" for name, n in counts.items())
    path = " → ".join(call["tool"] for call in TOOL_CALLS)
    print("\n=== TOOL CALLS ===")
    print(f"{len(TOOL_CALLS)} calls — {breakdown}")
    print(f"path: {path}")
    with open("tool_calls.jsonl", "w", encoding="utf-8") as f:
        for call in TOOL_CALLS:
            f.write(json.dumps(call) + "\n")

messages = [
    {"role": "system", "content": SYSTEM},
    {"role": "user", "content": TASK},
]
print(f"USER: {TASK}\n")

while True:
    resp = client.chat.completions.create(
        model=MODEL, messages=messages, tools=[BASH_TOOL],
    )
    msg = resp.choices[0].message
    messages.append(msg.model_dump(exclude_none=True))

    if not msg.tool_calls:
        print(f"\n=== FINAL RESPONSE ===\n\n{msg.content or ''}")
        write_tool_telemetry()
        break

    for tc in msg.tool_calls:
        args = json.loads(tc.function.arguments)
        TOOL_CALLS.append({"tool": tc.function.name, "args": args})
        print(f"> bash({args['command']!r})")
        result = bash(**args)
        if len(result) < 400:
            preview = result
        else:
            preview = result[:400] + "...[truncated]"
        print(f"  {preview}\n")
        messages.append({
            "role": "tool", "tool_call_id": tc.id, "content": result,
        })
