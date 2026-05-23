"""
Episode 2 — Tools

Adds four general primitives (read, write, edit, grep) alongside bash, plus a
tiny @tool decorator (~25 lines) that builds the JSON-schema tool definition
from a Python function's signature. Naive stop condition is still in place;
done tool arrives in Ep 3.

See ../../README.md and ../../../spec/episode-02.md for context.
"""
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import get_type_hints

from dotenv import load_dotenv
from openai import OpenAI

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# --- 1. Sandbox reset.
INITIAL = Path("initial")
SANDBOX = Path("sandbox")
if SANDBOX.exists():
    shutil.rmtree(SANDBOX)
shutil.copytree(INITIAL, SANDBOX)

# --- 2. LLM client.
load_dotenv(Path("../../.env"))
BASE_URL = os.environ.get("OPENAI_BASE_URL") or ""
API_KEY = os.environ.get("ANTHROPIC_API_KEY") if "anthropic" in BASE_URL else os.environ.get("OPENAI_API_KEY")
MODEL = os.environ.get("OPENAI_MODEL", "gpt-5-mini")
client = OpenAI(api_key=API_KEY, base_url=BASE_URL or None)


# --- 3. The @tool decorator: function signature -> JSON-schema tool definition.
def tool(description: str):
    """Attach a JSON-schema tool definition to a Python function."""
    json_types = {str: "string", int: "integer", float: "number", bool: "boolean"}

    def decorator(func):
        sig = inspect.signature(func)
        hints = get_type_hints(func)
        properties, required = {}, []
        for name, param in sig.parameters.items():
            t = hints.get(name, str)
            properties[name] = {"type": json_types.get(t, "string")}
            if param.default is inspect.Parameter.empty:
                required.append(name)
        func.tool_definition = {
            "type": "function",
            "function": {
                "name": func.__name__,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                    "additionalProperties": False,
                },
            },
        }
        return func
    return decorator


# --- 4. The tools. All paths resolve inside SANDBOX.
def _safe_path(path: str) -> Path:
    """Resolve `path` inside SANDBOX. Raises if it escapes."""
    resolved = (SANDBOX / path).resolve()
    resolved.relative_to(SANDBOX.resolve())  # raises ValueError if outside
    return resolved


@tool("Execute a shell command in the working directory and return its output.")
def bash(command: str) -> str:
    result = subprocess.run(  # noqa: S602  # nosec
        command, shell=True, capture_output=True, text=True,
        cwd=SANDBOX, timeout=30,
        encoding="utf-8", errors="replace",
        check=False,
    )
    return (result.stdout + result.stderr).strip() or "(no output)"


@tool("Read a file's contents, prefixed with line numbers.")
def read(path: str) -> str:
    p = _safe_path(path)
    if not p.exists():
        return f"Error: {path} does not exist."
    if p.is_dir():
        return f"Error: {path} is a directory. Use bash to list its contents."
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(f"{i+1:5d}\t{line}" for i, line in enumerate(lines))


@tool("Write content to a file, overwriting any existing content. Creates parent directories.")
def write(path: str, content: str) -> str:
    p = _safe_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"Wrote {len(content)} bytes to {path}."


@tool("Replace the first occurrence of old_string with new_string in a file. Errors if old_string isn't unique.")
def edit(path: str, old_string: str, new_string: str) -> str:
    p = _safe_path(path)
    if not p.exists():
        return f"Error: {path} does not exist."
    if p.is_dir():
        return f"Error: {path} is a directory."
    text = p.read_text(encoding="utf-8", errors="replace")
    count = text.count(old_string)
    if count == 0:
        return f"Error: old_string not found in {path}."
    if count > 1:
        return f"Error: old_string appears {count} times in {path}; provide more context to make it unique."
    p.write_text(text.replace(old_string, new_string, 1), encoding="utf-8")
    return f"Replaced 1 occurrence in {path}."


@tool("Search for a regex pattern under a path. Returns matches as relative/path:line: text.")
def grep(pattern: str, path: str = ".") -> str:
    try:
        regex = re.compile(pattern)
    except re.error as e:
        return f"Error: invalid regex: {e}"
    root = _safe_path(path)
    if root.is_file():
        files = [root]
    else:
        files = [p for p in root.rglob("*") if p.is_file()]
    results = []
    for f in files:
        try:
            for i, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                if regex.search(line):
                    rel = f.relative_to(SANDBOX)
                    results.append(f"{rel}:{i}: {line[:200]}")
                    if len(results) >= 50:
                        return "\n".join(results) + "\n... (truncated at 50 matches)"
        except Exception:
            continue  # skip binary / unreadable
    return "\n".join(results) if results else f"No matches for {pattern!r}."


# --- 5. Tool registry: name -> callable, plus the list of schemas for the LLM.
TOOLS = [bash, read, write, edit, grep]
TOOLS_BY_NAME = {t.__name__: t for t in TOOLS}
TOOL_DEFS = [t.tool_definition for t in TOOLS]


# --- 6. The agent loop. Identical to Ep 1 except for the dispatch by tool name.
SYSTEM = (
    "You are a coding assistant operating inside a sandboxed working "
    "directory. Use the available tools to investigate, modify, and "
    "verify code. Ground claims in what you actually observe; don't "
    "guess. When the task is complete, stop calling tools and produce "
    "a clear answer."
)
TASK = """I'm seeing this when I run pytest in this repo:

FAILED tests/test_renderer.py::test_fixture_pair[escaped_backticks]
AssertionError: rendered HTML doesn't match expected.
See tests/fixtures/escaped_backticks.md / escaped_backticks.html
for the input and what the output should be.

Can you figure out what's wrong and fix it?"""

messages = [
    {"role": "system", "content": SYSTEM},
    {"role": "user", "content": TASK},
]
print(f"USER: {TASK}\n")

total_in = total_out = 0
iteration = 0

while True:
    iteration += 1
    resp = client.chat.completions.create(
        model=MODEL, messages=messages, tools=TOOL_DEFS,
    )
    u = resp.usage
    total_in += u.prompt_tokens
    total_out += u.completion_tokens
    print(f"  [iter {iteration}: in={u.prompt_tokens}, out={u.completion_tokens}]\n")

    msg = resp.choices[0].message
    messages.append(msg.model_dump(exclude_none=True))

    if not msg.tool_calls:
        print(f"\n=== FINAL RESPONSE ===\n\n{msg.content or ''}")
        print(f"\n=== TOKEN USAGE ===\niterations: {iteration}  input: {total_in:,}  output: {total_out:,}  total: {total_in + total_out:,}")
        break

    for tc in msg.tool_calls:
        fn = TOOLS_BY_NAME[tc.function.name]
        args = json.loads(tc.function.arguments)
        arg_preview = ", ".join(f"{k}={v!r}" if len(repr(v)) < 60 else f"{k}=<{len(str(v))} chars>" for k, v in args.items())
        print(f"> {tc.function.name}({arg_preview})")
        result = fn(**args)
        preview = result if len(result) < 400 else result[:400] + "...[truncated]"
        print(f"  {preview}\n")
        messages.append({
            "role": "tool", "tool_call_id": tc.id, "content": result,
        })
