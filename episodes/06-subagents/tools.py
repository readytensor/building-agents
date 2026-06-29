"""
Episode 6 — Subagents (tools)

The agent's action space — the same six file primitives carried forward
(bash, list_files, read, write, edit, grep) plus the tiny @tool decorator
that builds each tool's JSON-schema from its signature.

One difference from Ep 5's tools.py: the @tool decorator here does NOT record
tool-call telemetry itself. Ep 6 runs many agents concurrently (the
orchestrator plus parallel workers), so each call has to be tagged with WHICH
agent made it — and the decorator can't see that. run_agent (in agent.py)
records each call with its worker label instead. This file just owns the
shared TOOL_CALLS list + the writer; agent.py appends the tagged records.

TOOL_FUNCTIONS is the menu of always-available file tools. A worker's actual
toolset is a per-call subset of this (plus closures + skill tools), assembled
in run_agent from the worker's .agents/<name>.md allowlist.

Imports nothing from agent.py (one-way `agent → tools`). Every tool resolves
paths inside SANDBOX, defined here; agent.py owns the sandbox *reset*.

See ../../README.md for context.
"""
import inspect
import json
import os
import re
import subprocess
from pathlib import Path
from typing import get_type_hints

# The working directory every tool is bounded to. agent.py resets it to a clean
# copy of initial/ at the start of each run.
SANDBOX = Path("sandbox")

# --- Tool-call telemetry. The list is shared across all agents; run_agent
# appends one record per call, tagged with the worker that made it. Written to
# tool_calls.jsonl at the end of the run; the harness (run.py) renders it.
TOOL_CALLS = []  # list of {"round": n, "agent": label, "tool": name, "args": {...}}


def write_tool_telemetry():
    """Write the tool calls made this run to tool_calls.jsonl, one JSON object
    per line in call order (each tagged with the agent that made it). Recording
    only — rendering a summary is left to whatever reads the file."""
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


# --- The working tools. All paths resolve inside SANDBOX.
def _safe_path(path: str) -> Path:
    """Resolve `path` inside SANDBOX. Raises if it escapes."""
    resolved = (SANDBOX / path).resolve()
    resolved.relative_to(SANDBOX.resolve())  # raises ValueError if outside
    return resolved


@tool("Execute a shell command in the working directory and return its output.")
def bash(command: str) -> str:
    # cwd=SANDBOX sets the starting directory for convenience and
    # reproducibility. It is NOT a security boundary: with shell=True the
    # command can cd elsewhere, use absolute paths, or read and write anything
    # this process can. Actually containing a real shell needs OS-level
    # isolation (a container, or a sandbox like macOS Seatbelt / Linux
    # bubblewrap, the way real agents such as Claude Code do it), which is out
    # of scope for this toy. So run it against code you trust, on a machine you
    # don't mind it touching. check=False: non-zero exits return as output so
    # the model can adapt.
    proc = subprocess.Popen(  # noqa: S602  # nosec
        command, shell=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        cwd=SANDBOX, encoding="utf-8", errors="replace",
        start_new_session=(os.name != "nt"),  # POSIX: own group so we can kill the whole tree
    )
    try:
        output = proc.communicate(timeout=30)[0]
    except subprocess.TimeoutExpired:
        # Kill the WHOLE process tree, not just the shell. With shell=True the
        # real command runs as a grandchild of the shell; killing only the shell
        # leaves the grandchild alive, still holding the output pipe — which
        # deadlocks the drain (an unbounded loop would then hang forever).
        # taskkill /T (Windows) and killpg (POSIX) take the descendants down too.
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, check=False)
        else:
            import signal
            killpg = getattr(os, "killpg", None)      # POSIX-only; absent on Windows,
            getpgid = getattr(os, "getpgid", None)    # so this branch never runs there
            if killpg and getpgid:
                try:
                    killpg(getpgid(proc.pid), getattr(signal, "SIGKILL", 9))
                except ProcessLookupError:
                    pass
        if proc.poll() is None:   # if the tree-kill missed, at least kill the shell
            proc.kill()
        try:
            proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        return (
            "Error: command timed out after 30s and was killed (whole process "
            "tree). Avoid long-running or interactive commands, watch for code "
            "that can loop forever, and scope file searches to the working directory."
        )
    output = (output or "").strip()
    if len(output) > 20_000:                 # cap transcript growth from chatty commands
        output = output[:20_000] + "\n...[truncated]"
    if proc.returncode:                      # surface failures so the model can adapt
        output += f"\n(exit code {proc.returncode})"
    return output or "(no output)"


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


# --- The menu of always-available file tools, by name. A worker's actual
# toolset is assembled per-call in run_agent from its allowlist (plus the
# planning/skills closures and any skill-provided tools).
TOOL_FUNCTIONS = {fn.__name__: fn for fn in [bash, list_files, read, write, edit, grep]}
