"""
Episode 4 — Planning (with `think` as a related reasoning-strategy tool)

Adds two reasoning-strategy tools to Ep 3's agent:

1. `write_plan(steps)` — Claude Code-style structured plan that lives in
   agent state (not message history) and is injected into the model's
   context on every iteration. Persistent across compaction. For
   tracking progress through multi-step tasks.

2. `think(thought)` — a no-op tool that echoes the thought back. Forces
   the model to externalize reasoning before action. For in-the-moment
   hard problems and architectural decisions.

The two tools have distinct purposes — see their descriptions in the
@tool docstrings. The main example here focuses on planning; think
is included as a related pattern worth knowing about.

Everything else is unchanged from Ep 3: 6 working tools (bash/read/write/
edit/grep/done), @tool decorator, sandbox reset, compaction.

NOTE — DEV-TIME SDK SWAP (2026-05-23):
This file temporarily uses the native Anthropic SDK with prompt caching
to cut development iteration cost. The series's locked decision is to
use the openai SDK against Chat Completions for provider portability;
the published companion code will be translated back to that shape
before shipping. See ../../../CLAUDE.md for the locked decision.

See ../../README.md for context.
"""
import functools
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import get_type_hints

import anthropic
from dotenv import load_dotenv

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# --- 1. Sandbox reset.
INITIAL = Path("initial")
SANDBOX = Path("sandbox")
if SANDBOX.exists():
    shutil.rmtree(SANDBOX)
shutil.copytree(INITIAL, SANDBOX)

# --- 2. LLM client.
load_dotenv(Path("../../.env"))
client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
MODEL = os.environ.get("LLM_AGENT_MODEL", "claude-sonnet-4-6")
MAX_TOKENS = int(os.environ.get("LLM_MAX_TOKENS", 4096))

# --- Knobs.
COMPACTION_THRESHOLD = int(os.environ.get("EP3_THRESHOLD", 30_000))
KEEP_LAST_ITERATIONS = int(os.environ.get("EP3_KEEP", 4))
MAX_ITERATIONS = int(os.environ.get("EP4_MAX_ITER", 150))

# --- Tool-call telemetry: record every tool the agent invokes, in order, so
# we can see the path it took and how many calls it made (this varies run to
# run). Summarized and written to tool_calls.jsonl at the end of the run.
TOOL_CALLS = []  # list of {"tool": name, "args": {...}} in call order


# --- 3. The @tool decorator (Anthropic shape).
def tool(description: str):
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
        def wrapper(**kwargs):
            # Record the call before invoking, so tools that raise (e.g. done)
            # are still captured and the recorded path stays complete.
            TOOL_CALLS.append({"tool": func.__name__, "args": kwargs})
            return func(**kwargs)

        wrapper.tool_definition = {
            "name": func.__name__,
            "description": description,
            "input_schema": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }
        return wrapper
    return decorator


# --- 4. The done tool.
class TaskComplete(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


@tool("Signal that the task is complete. Pass a clear summary of what you did.")
def done(message: str) -> str:
    raise TaskComplete(message)


# --- 5. The five working tools (unchanged from Ep 3).
def _safe_path(path: str) -> Path:
    resolved = (SANDBOX / path).resolve()
    resolved.relative_to(SANDBOX.resolve())
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
                    rel = f.relative_to(SANDBOX.resolve())
                    results.append(f"{rel}:{i}: {line[:200]}")
                    if len(results) >= 50:
                        return "\n".join(results) + "\n... (truncated at 50 matches)"
        except Exception:
            continue
    return "\n".join(results) if results else f"No matches for {pattern!r}."


# --- 6. The planning tool. Claude Code TodoWrite-style.
# Plan lives in agent state (not message history) so it survives compaction
# and is always re-injected fresh into context on every LLM call.
CURRENT_PLAN: list[dict] = []


def _format_plan(plan: list[dict]) -> str:
    if not plan:
        return "(no plan set)"
    lines = []
    icons = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]"}
    for i, step in enumerate(plan, 1):
        icon = icons.get(step.get("status", "pending"), "[?]")
        content = step.get("content", "")
        lines.append(f"  {i}. {icon} {content}")
    return "\n".join(lines)


@tool(
    "Set or update your working plan for a MULTI-STEP TASK. Pass the FULL "
    "current state of the plan as a list of steps. Each step can be either "
    "(a) a string describing the step, or (b) a dict with 'content' (string) "
    "and 'status' (one of 'pending', 'in_progress', 'completed'). Call this "
    "at the start of a task with multiple distinct subtasks, and again "
    "whenever you complete a step or revise your approach. The plan is "
    "always visible to you in subsequent iterations. "
    "USE THIS FOR: tracking progress through multiple distinct subtasks. "
    "NOT FOR: in-the-moment reasoning about a single hard problem — for that, "
    "use the `think` tool."
)
def write_plan(steps) -> str:
    # Defensive: schema typing for list-of-X isn't tight, so the model sometimes
    # sends `steps` as a JSON-encoded string instead of an actual array. Recover.
    if isinstance(steps, str):
        try:
            steps = json.loads(steps)
        except Exception:
            return "Error: `steps` must be a list of steps, not a single string."
    if not isinstance(steps, list):
        return f"Error: `steps` must be a list, got {type(steps).__name__}."
    CURRENT_PLAN.clear()
    for step in steps:
        if isinstance(step, str):
            CURRENT_PLAN.append({"content": step, "status": "pending"})
        elif isinstance(step, dict):
            CURRENT_PLAN.append({
                "content": str(step.get("content", "")),
                "status": step.get("status", "pending"),
            })
        # silently skip any other shape
    return f"Plan updated ({len(CURRENT_PLAN)} steps):\n{_format_plan(CURRENT_PLAN)}"


@tool(
    "Externalize your reasoning about a hard problem or decision. Pass a "
    "thought as a string; it is echoed back unchanged. The act of writing "
    "the thought out forces explicit reasoning before action. "
    "USE THIS FOR: weighing alternative approaches before choosing one, "
    "reasoning through a tricky edge case, untangling a confusing problem. "
    "NOT FOR: tracking multi-step task progress — for that, use `write_plan`."
)
def think(thought: str) -> str:
    return thought


# --- 7. Tool registry.
TOOLS = [bash, read, write, edit, grep, done, write_plan, think]
TOOLS_BY_NAME = {t.__name__: t for t in TOOLS}
TOOL_DEFS = [t.tool_definition for t in TOOLS]


# --- 8. Cache-control helpers (Anthropic prompt caching).
# Strategy: explicit markers on system + last tool (immutable prefix),
# plus top-level `cache_control` for AUTOMATIC rolling-window caching
# of the growing message history. The automatic mode is what Anthropic
# recommends for multi-turn agents — it handles 20-block lookback and
# threshold rules internally instead of tracking them by hand.
# A hand-rolled `_with_rolling_cache` on messages[-1] is fragile across
# long runs, which is why the automatic mode is preferred here.

def _system_cached():
    # System has two parts: a stable base (cached) plus an optional
    # current-plan block appended after. Putting the plan in system
    # rather than mutating the last user message keeps the message
    # prefix byte-stable across iterations — that's what lets the
    # message cache actually hit on subsequent calls.
    base = {"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}
    if CURRENT_PLAN:
        plan_block = {
            "type": "text",
            "text": f"\n\n[CURRENT PLAN]\n{_format_plan(CURRENT_PLAN)}\n[end plan]",
        }
        return [base, plan_block]
    return [base]


def _tools_cached():
    out = [dict(td) for td in TOOL_DEFS]
    out[-1] = {**out[-1], "cache_control": {"type": "ephemeral"}}
    return out


# --- 10. Compaction (unchanged shape from Ep 3, retranslated to Anthropic API).
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
    out = []
    for m in messages:
        role = m.get("role", "?")
        content = m.get("content", "")
        if isinstance(content, str):
            out.append(f"{role.upper()}: {content}")
            continue
        text_parts = []
        tool_use_lines = []
        tool_result_lines = []
        for b in content:
            btype = b.get("type") if isinstance(b, dict) else None
            if btype == "text":
                text_parts.append(b.get("text", ""))
            elif btype == "tool_use":
                tool_use_lines.append(
                    f"  -> {b.get('name')}({json.dumps(b.get('input'), default=str)})"
                )
            elif btype == "tool_result":
                tc = b.get("content", "")
                if isinstance(tc, list):
                    parts = []
                    for x in tc:
                        if isinstance(x, dict):
                            parts.append(x.get("text", ""))
                        else:
                            parts.append(str(x))
                    tc = " ".join(parts)
                tc = str(tc)
                preview = tc if len(tc) < 500 else tc[:500] + "...[truncated]"
                tool_result_lines.append(f"TOOL RESULT: {preview}")
        if role == "assistant":
            line = "ASSISTANT: " + " ".join(text_parts)
            if tool_use_lines:
                line += "\n" + "\n".join(tool_use_lines)
            out.append(line)
        elif role == "user":
            if tool_result_lines:
                out.extend(tool_result_lines)
            if text_parts:
                out.append(f"USER: {' '.join(text_parts)}")
        else:
            out.append(f"{role.upper()}: {' '.join(text_parts)}")
    return "\n\n".join(out)


def _extract_text(content):
    if isinstance(content, str):
        return content
    parts = []
    for b in content:
        if isinstance(b, dict) and b.get("type") == "text":
            parts.append(b.get("text", ""))
    return " ".join(parts)


def compact(messages):
    asst_positions = [i for i, m in enumerate(messages) if m.get("role") == "assistant"]
    if len(asst_positions) <= KEEP_LAST_ITERATIONS:
        return messages, False, 0, 0
    head = messages[:1]  # original user task (no system role in Anthropic shape)
    tail_start = asst_positions[-KEEP_LAST_ITERATIONS]
    middle = messages[1:tail_start]
    tail = messages[tail_start:]
    if not middle:
        return messages, False, 0, 0

    summary_resp = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SUMMARIZER_PROMPT,
        messages=[
            {"role": "user", "content": (
                f"Original task:\n{_extract_text(head[0]['content'])}\n\n"
                f"Transcript to summarize:\n{_format_as_transcript(middle)}"
            )},
        ],
    )
    summary_text = "".join(b.text for b in summary_resp.content if b.type == "text")
    summary_msg = {
        "role": "user",
        "content": (
            "[CONTEXT COMPACTED — earlier transcript summarized below.]\n\n"
            f"{summary_text}\n\n"
            "[End of summary. Continue with the most recent turns.]"
        ),
    }
    # After compaction, the new messages[1] (summary_msg) is a `user` role. The
    # next message in `tail` starts with the oldest-preserved assistant turn, so
    # alternation (user -> assistant -> user -> ...) is preserved.
    su = summary_resp.usage
    return head + [summary_msg] + tail, True, su.input_tokens, su.output_tokens


# --- 11. Block-to-dict helper for persisting assistant messages.
def _block_to_dict(b):
    if b.type == "text":
        return {"type": "text", "text": b.text}
    if b.type == "tool_use":
        return {"type": "tool_use", "id": b.id, "name": b.name, "input": b.input}
    return b.model_dump()


def write_tool_telemetry():
    """Write the tool calls made this run to tool_calls.jsonl, one JSON object
    per line in call order. Recording only — rendering a summary is left to
    whatever reads the file."""
    with open("tool_calls.jsonl", "w", encoding="utf-8") as f:
        for call in TOOL_CALLS:
            f.write(json.dumps(call) + "\n")


def write_metrics():
    """Write this run's token usage to metrics.json. Recording only — the
    harness (run.py) reads this and renders the summary. Records cache and
    compaction tokens and the reasoning-tool counts so the harness can show
    them; with prompt caching, per_iter carries [in, out, cache_w, cache_r]."""
    metrics = {
        "agents": [{
            "label": "agent",
            "iterations": iteration,
            "input_tokens": total_in,
            "output_tokens": total_out,
            "cache_write": total_cache_w,
            "cache_read": total_cache_r,
            "compactions": compactions_fired,
            "compact_in": compact_in,
            "compact_out": compact_out,
            "reasoning": {"write_plan": plan_writes, "think": think_calls},
            "per_iter": per_iter,
        }],
        "inputs": {"system": SYSTEM, "task": TASK},
        "config": {
            "MODEL": MODEL,
            "COMPACTION_THRESHOLD": COMPACTION_THRESHOLD,
            "KEEP_LAST_ITERATIONS": KEEP_LAST_ITERATIONS,
        },
    }
    with open("metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)


# --- 12. The agent loop.
SYSTEM = (
    "You are a coding assistant operating inside a sandboxed working "
    "directory. Use the available tools to investigate, modify, and "
    "verify code. Ground claims in what you actually observe; don't "
    "guess. When the task is complete, call done() with a clear summary "
    "of what you did."
)
TASK = """I want to add support for reference-style links to our markdown
library. They look like this:

    Here is a [link][myref] in text.

    [myref]: https://example.com "Optional title"

The link definitions (the `[id]: url "title"` lines) get collected from
the document, and inline `[text][id]` references resolve to <a> elements
using those URLs. The definition lines themselves should NOT appear in
the rendered output.

I've added a test fixture at tests/fixtures/reference_style_links.md and
tests/fixtures/reference_style_links.html showing the expected behavior.
Right now pytest fails on it because the feature isn't implemented.

Can you add reference-style links? Make sure all other tests still pass."""

messages = [
    {"role": "user", "content": TASK},
]
print(f"USER: {TASK}\n")

total_in = total_out = 0
total_cache_w = total_cache_r = 0
compact_in = compact_out = 0
iteration = 0
compactions_fired = 0
plan_writes = 0
think_calls = 0
per_iter = []

try:
    while iteration < MAX_ITERATIONS:
        iteration += 1

        resp = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=_system_cached(),
            tools=_tools_cached(),
            messages=messages,
            extra_body={"cache_control": {"type": "ephemeral"}},
        )
        u = resp.usage
        cw = getattr(u, "cache_creation_input_tokens", 0) or 0
        cr = getattr(u, "cache_read_input_tokens", 0) or 0
        total_in += u.input_tokens
        total_out += u.output_tokens
        total_cache_w += cw
        total_cache_r += cr
        per_iter.append([u.input_tokens, u.output_tokens, cw, cr])

        # Persist the assistant turn.
        assistant_blocks = [_block_to_dict(b) for b in resp.content]
        messages.append({"role": "assistant", "content": assistant_blocks})

        tool_uses = [b for b in resp.content if b.type == "tool_use"]

        if not tool_uses:
            text = "".join(b.text for b in resp.content if b.type == "text")
            print(f"\n=== FINAL RESPONSE (no done tool called) ===\n\n{text}")
            break

        # Execute every tool call; collect results into a single user message.
        tool_results = []
        for tu in tool_uses:
            try:
                fn = TOOLS_BY_NAME[tu.name]
                args = tu.input or {}
                parts = []
                for k, v in args.items():
                    if len(repr(v)) < 60:
                        parts.append(f"{k}={v!r}")
                    else:
                        parts.append(f"{k}=<{len(str(v))} chars>")
                arg_preview = ", ".join(parts)
                print(f"> {tu.name}({arg_preview})")
                result = fn(**args)
                if tu.name == "write_plan":
                    plan_writes += 1
                elif tu.name == "think":
                    think_calls += 1
            except (TypeError, KeyError, ValueError) as e:
                result = f"Error executing {tu.name}: {type(e).__name__}: {e}"
                print(f"  ! {result}")
            preview = result if len(result) < 2000 else result[:2000] + "...[truncated]"
            print(f"  {preview}\n")
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu.id,
                "content": result,
            })
        messages.append({"role": "user", "content": tool_results})

        # Compaction check. With caching, `input_tokens` reports only the
        # uncached delta — the true effective prompt size is input + cache_r
        # + cache_w. We compare that sum to the threshold so compaction
        # still fires as the message history grows.
        if u.input_tokens + cr + cw > COMPACTION_THRESHOLD:
            before = len(messages)
            messages, did, ci, co = compact(messages)
            if did:
                compactions_fired += 1
                compact_in += ci
                compact_out += co
                print(f"  [COMPACTION FIRED — {before} messages -> {len(messages)}, "
                      f"summarizer in={ci} out={co}]\n")
    else:
        print(f"\n=== MAX_ITERATIONS REACHED ({MAX_ITERATIONS}) — aborting ===")

except TaskComplete as e:
    print(f"\n=== TASK COMPLETE ===\n\n{e.message}")

write_tool_telemetry()
write_metrics()
