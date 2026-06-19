"""
Episode 4 — Planning & Thinking (tools)

The agent's action space — carried forward from Ep 3 unchanged: the same six
general primitives (bash, list_files, read, write, edit, grep) plus the tiny
@tool decorator that builds each tool's JSON-schema from its signature.

Ep 4's new tools (write_plan, think) are tied to the plan-injection
mechanism, so they live in planning.py — not here. This file is
identical to Ep 3's tools.py: the file primitives don't change this episode.

As in Ep 3, the tools live here, separate from the agent loop, and import
nothing from agent.py (one-way `agent → tools`). Every tool resolves paths
inside SANDBOX, defined here; agent.py owns the sandbox *reset*.

See ../../README.md for context.
"""
import functools
import inspect
import json
import re
import subprocess
from pathlib import Path
from typing import get_type_hints

# The working directory every tool is bounded to. agent.py resets it to a clean
# copy of initial/ at the start of each run.
SANDBOX = Path("sandbox")

# --- Tool-call telemetry: record every tool the agent invokes, in order, so we
# can see the path it took and how many calls it made (this varies run to run).
# Recorded in the @tool wrapper below and written to tool_calls.jsonl at the end
# of the run; the harness (run.py) renders the summary.
TOOL_CALLS = []  # list of {"round": n, "tool": name, "args": {...}} in call order
CURRENT_ROUND = 0  # the agent-loop iteration; agent.py sets it each turn so every
# recorded tool call is tagged with the round (model call) it happened in


def write_tool_telemetry():
    """Write the tool calls made this run to tool_calls.jsonl, one JSON object
    per line in call order. Recording only — rendering a summary is left to
    whatever reads the file."""
    with open("tool_calls.jsonl", "w", encoding="utf-8") as f:
        for call in TOOL_CALLS:
            f.write(json.dumps(call) + "\n")


# --- The @tool decorator: function signature -> JSON-schema tool definition.
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

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Record the call before running it, so the path stays correct even
            # if the tool raises.
            bound = sig.bind(*args, **kwargs)
            TOOL_CALLS.append({"round": CURRENT_ROUND, "tool": func.__name__, "args": dict(bound.arguments)})
            return func(*args, **kwargs)

        wrapper.tool_definition = {
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
        return wrapper
    return decorator


# --- The working tools. All paths resolve inside SANDBOX.
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


@tool("List files under a path (recursive), one relative path per line — a reliable cross-platform alternative to shell find/ls/dir. Skips caches and VCS dirs.")
def list_files(path: str = ".") -> str:
    sandbox = SANDBOX.resolve()
    root = _safe_path(path)
    if root.is_file():
        return str(root.relative_to(sandbox))
    skip = {"__pycache__", ".pytest_cache", ".git", ".venv", ".ruff_cache"}
    files = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and not any(part in skip for part in p.parts):
            files.append(str(p.relative_to(sandbox)))
            if len(files) >= 200:
                files.append("... (truncated at 200 files)")
                break
    return "\n".join(files) if files else "(no files)"


@tool("Read a file's contents, prefixed with line numbers.")
def read(path: str) -> str:
    p = _safe_path(path)
    if not p.exists():
        return f"Error: {path} does not exist."
    if p.is_dir():
        return f"Error: {path} is a directory. Use bash to list its contents."
    lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    numbered = [f"{i+1:5d}\t{line}" for i, line in enumerate(lines)]
    return "\n".join(numbered)


@tool("Write content to a file, overwriting any existing content. Creates parent directories.")
def write(path: str, content: str) -> str:
    p = _safe_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"Wrote {len(content)} bytes to {path}."


@tool("Replace old_string with new_string in a file. Replaces a single occurrence and errors if old_string isn't unique; pass replace_all=true to replace every occurrence (e.g. renaming a symbol).")
def edit(path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
    p = _safe_path(path)
    if not p.exists():
        return f"Error: {path} does not exist."
    if p.is_dir():
        return f"Error: {path} is a directory."
    text = p.read_text(encoding="utf-8", errors="replace")
    count = text.count(old_string)
    if count == 0:
        return f"Error: old_string not found in {path}."
    if count > 1 and not replace_all:
        return f"Error: old_string appears {count} times in {path}; pass replace_all=true to replace all, or add more context to make it unique."
    p.write_text(text.replace(old_string, new_string), encoding="utf-8")
    return f"Replaced {count} occurrence(s) in {path}."


@tool("Search for a regex pattern under a path. Returns matches as relative/path:line: text.")
def grep(pattern: str, path: str = ".") -> str:
    try:
        regex = re.compile(pattern)
    except re.error as e:
        return f"Error: invalid regex: {e}"
    sandbox = SANDBOX.resolve()
    root = _safe_path(path)
    if root.is_file():
        files = [root]
    else:
        files = [p for p in root.rglob("*") if p.is_file()]
    results = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
            for i, line in enumerate(text.splitlines(), 1):
                if regex.search(line):
                    rel = f.relative_to(sandbox)
                    results.append(f"{rel}:{i}: {line[:200]}")
                    if len(results) >= 50:
                        return "\n".join(results) + "\n... (truncated at 50 matches)"
        except Exception:
            continue  # skip binary / unreadable
    return "\n".join(results) if results else f"No matches for {pattern!r}."


# --- Tool registry: name -> callable, plus the list of schemas for the LLM.
# Ep 4 extends this with the planning tools in agent.py (TOOLS + [write_plan,
# think]); these six are the carried-forward base.
TOOLS = [bash, list_files, read, write, edit, grep]
TOOLS_BY_NAME = {t.__name__: t for t in TOOLS}
TOOL_DEFS = [t.tool_definition for t in TOOLS]
