"""
Episode 3 — Context

Adds two paired additions to Ep 2's agent:

1. The done tool — explicit `TaskComplete` signal replaces the naive stop.
2. Rolling-summary compaction — when a single LLM call's input tokens cross
   COMPACTION_THRESHOLD, the older middle of the message history gets
   summarized via a second LLM call and replaced with one summary message.

The system prompt gets one new sentence (call done() when complete). All other
prior behavior is unchanged: same 5 tools, same @tool decorator, same
sandbox reset, same provider-agnostic OpenAI SDK setup.

See ../../README.md for context.
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
if "anthropic" in BASE_URL:
    API_KEY = os.environ.get("ANTHROPIC_API_KEY")
else:
    API_KEY = os.environ.get("OPENAI_API_KEY")
MODEL = os.environ.get("OPENAI_MODEL", "gpt-5-mini")
client = OpenAI(api_key=API_KEY, base_url=BASE_URL or None)

# --- Compaction knobs. Env-overridable; defaults shown below.
COMPACTION_THRESHOLD = int(os.environ.get("EP3_THRESHOLD", 30_000))  # input tokens per single LLM call.
KEEP_LAST_ITERATIONS = int(os.environ.get("EP3_KEEP", 4))            # recent assistant rounds preserved uncompacted.
MAX_ITERATIONS = int(os.environ.get("EP3_MAX_ITER", 150))  # safety cap to prevent an infinite loop.


# --- 3. The @tool decorator.
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


# --- 4. The done tool: explicit completion signal.
class TaskComplete(Exception):
    """Raised by the done tool to signal explicit task completion."""
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


@tool("Signal that the task is complete. Pass a clear summary of what you did.")
def done(message: str) -> str:
    raise TaskComplete(message)


# --- 5. The five working tools. All paths resolve inside SANDBOX.
def _safe_path(path: str) -> Path:
    resolved = (SANDBOX / path).resolve()
    # raises ValueError if path escapes SANDBOX (path-traversal guard)
    resolved.relative_to(SANDBOX.resolve())
    return resolved


@tool("Execute a shell command in the working directory and return its output.")
def bash(command: str) -> str:
    result = subprocess.run(
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
    numbered = []
    for i, line in enumerate(lines):
        numbered.append(f"{i+1:5d}\t{line}")
    return "\n".join(numbered)


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
            text = f.read_text(encoding="utf-8", errors="replace")
            for i, line in enumerate(text.splitlines(), 1):
                if regex.search(line):
                    rel = f.relative_to(SANDBOX)
                    results.append(f"{rel}:{i}: {line[:200]}")
                    if len(results) >= 50:
                        return "\n".join(results) + "\n... (truncated at 50 matches)"
        except Exception:
            continue
    return "\n".join(results) if results else f"No matches for {pattern!r}."


# --- 6. Tool registry: name -> callable, plus the list of schemas for the LLM.
TOOLS = [bash, read, write, edit, grep, done]
TOOLS_BY_NAME = {t.__name__: t for t in TOOLS}
TOOL_DEFS = [t.tool_definition for t in TOOLS]


# --- 7. Compaction: summarize the middle of the message history when context grows.
SUMMARIZER_PROMPT = (
    "You're summarizing an in-progress coding-agent transcript so the agent can keep "
    "working with less context. Produce a concise structured summary that captures: "
    "(1) the user's original task, (2) what's been investigated so far (files read, "
    "what was found), (3) what's been changed so far (files written, edits applied), "
    "(4) what's still to do, (5) any errors encountered and how they were handled. "
    "Be terse but specific — the agent will continue from this summary, so don't "
    "omit anything that would force re-investigation."
)


def _format_as_transcript(messages):
    """Render a list of message dicts as a plain-text transcript for the summarizer."""
    out = []
    for m in messages:
        role = m.get("role", "?")
        content = m.get("content", "") or ""
        if role == "assistant":
            tcs = m.get("tool_calls") or []
            if tcs:
                tc_lines = []
                for tc in tcs:
                    fn = tc["function"]
                    tc_lines.append(f"  → {fn['name']}({fn['arguments']})")
                out.append(f"ASSISTANT: {content}\n" + "\n".join(tc_lines))
            else:
                out.append(f"ASSISTANT: {content}")
        elif role == "tool":
            preview = content if len(content) < 500 else content[:500] + "...[truncated]"
            out.append(f"TOOL RESULT: {preview}")
        else:
            out.append(f"{role.upper()}: {content}")
    return "\n\n".join(out)


def compact(messages):
    """Summarize the middle of `messages`, preserving system prompt, original task, last K rounds."""
    asst_positions = [i for i, m in enumerate(messages) if m.get("role") == "assistant"]
    if len(asst_positions) <= KEEP_LAST_ITERATIONS:
        return messages, False, 0, 0
    head = messages[:2]                            # system + original user task
    tail_start = asst_positions[-KEEP_LAST_ITERATIONS]
    middle = messages[2:tail_start]
    tail = messages[tail_start:]
    if not middle:
        return messages, False, 0, 0

    summarizer_msgs = [
        {"role": "system", "content": SUMMARIZER_PROMPT},
        {"role": "user", "content": (
            f"Original task:\n{head[1]['content']}\n\n"
            f"Transcript to summarize:\n{_format_as_transcript(middle)}"
        )},
    ]
    summary_resp = client.chat.completions.create(model=MODEL, messages=summarizer_msgs)
    summary_text = summary_resp.choices[0].message.content or ""
    summary_msg = {
        "role": "user",
        "content": (
            "[CONTEXT COMPACTED — earlier transcript summarized below.]\n\n"
            f"{summary_text}\n\n"
            "[End of summary. Continue with the most recent turns.]"
        ),
    }
    su = summary_resp.usage
    return head + [summary_msg] + tail, True, su.prompt_tokens, su.completion_tokens


# --- 8. The agent loop.
SYSTEM = (
    "You are a coding assistant operating inside a sandboxed working "
    "directory. Use the available tools to investigate, modify, and "
    "verify code. Ground claims in what you actually observe; don't "
    "guess. When the task is complete, call done() with a clear summary "
    "of what you did."
)
TASK = """I'm about to start adding inline tokens to the parser, and the
generic name `Node` for our AST type is going to get confusing. Can you
rename `Node` to `ASTNode` throughout the codebase? The change is purely
naming — semantics stay identical. All 43 tests should pass after."""

messages = [
    {"role": "system", "content": SYSTEM},
    {"role": "user", "content": TASK},
]
print(f"USER: {TASK}\n")

total_in = total_out = 0
compact_in = compact_out = 0
iteration = 0
compactions_fired = 0

try:
    while iteration < MAX_ITERATIONS:
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
            # No tool calls and no done() — model produced a final text response without
            # the done tool. Treat that as a soft completion but flag it.
            print(f"\n=== FINAL RESPONSE (no done tool called) ===\n\n{msg.content or ''}")
            break

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
            preview = result if len(result) < 400 else result[:400] + "...[truncated]"
            print(f"  {preview}\n")
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

        # Compaction check: fires when a single call's input crosses the threshold.
        if u.prompt_tokens > COMPACTION_THRESHOLD:
            before = len(messages)
            messages, did, ci, co = compact(messages)
            if did:
                compactions_fired += 1
                compact_in += ci
                compact_out += co
                print(f"  [COMPACTION FIRED — {before} messages → {len(messages)}, summarizer in={ci} out={co}]\n")
    else:
        print(f"\n=== MAX_ITERATIONS REACHED ({MAX_ITERATIONS}) — aborting ===")

except TaskComplete as e:
    print(f"\n=== TASK COMPLETE ===\n\n{e.message}")

print(f"\n=== TOKEN USAGE ===")
print(f"agent calls:        iterations={iteration}  input={total_in:,}  output={total_out:,}")
print(f"compaction calls:   count={compactions_fired}  input={compact_in:,}  output={compact_out:,}")
print(f"TOTAL:              input={total_in + compact_in:,}  output={total_out + compact_out:,}  grand_total={total_in + total_out + compact_in + compact_out:,}")
print(f"config: COMPACTION_THRESHOLD={COMPACTION_THRESHOLD:,}  KEEP_LAST_ITERATIONS={KEEP_LAST_ITERATIONS}")
