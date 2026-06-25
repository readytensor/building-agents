"""
Episode 5 — Skills

Adds a skills system to Ep 4's agent: lazy-loadable bundles of
procedural knowledge + tools, modeled on Claude Code's skill
abstraction (a SKILL.md per directory with YAML frontmatter + a
body of procedural instructions).

New additions on top of Ep 4:

1. `list_skills()` — walks .skills/, returns each skill's name +
   description (frontmatter only). Cheap discovery surface.

2. `load_skill(name)` — parses the named skill's SKILL.md, appends
   its body to the dynamic system-prompt block, registers any tools
   the skill provides for the rest of the run. Idempotent.

3. Skill-provided tools — only register when their owning skill is
   loaded:
     - `web_search` (research) — Anthropic's server-side web_search
        tool; activates when `research` loads
     - `fetch_url`  (research) — local urllib-based GET
     - `lint`       (verification) — shells out to ruff
     - `coverage`   (verification) — shells out to pytest-cov

4. `_system_with_dynamic()` extends Ep 4's `_system_cached()` to
   include loaded-skill bodies as additional dynamic text blocks
   after the cached base.

Two skills ship in `initial/.skills/`:
- `research` — when you need info you don't have in training
- `verification` — lint + coverage checks to run before signalling
  completion

Everything else inherited from Ep 4: planning + think, 5 working
tools, done, compaction, sandbox reset.

NOTE — DEV-TIME SDK SWAP (2026-05-24):
This file uses the native Anthropic SDK with prompt caching, same
as Ep 4. Two Anthropic-specific things must be translated when
shipping to the openai-SDK published code:
  - prompt caching itself (no openai-side equivalent for Anthropic
    cache_control)
  - the server-side web_search tool (translated to a custom local
    implementation against a real search API, or kept as an MCP
    tool, when shipping)
See ../../../CLAUDE.md.
"""
import functools
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, get_type_hints

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
MAX_ITERATIONS = int(os.environ.get("EP5_MAX_ITER", 200))
WEB_SEARCH_MAX_USES = int(os.environ.get("EP5_WEB_SEARCH_MAX", 10))

# --- Tool-call telemetry: record every tool the agent invokes, in order, so
# we can see the path it took and how many calls it made (this varies run to
# run). Summarized and written to tool_calls.jsonl at the end of the run.
TOOL_CALLS = []  # list of {"round": n, "tool": name, "args": {...}} in call order
CURRENT_ROUND = 0  # the agent-loop iteration; the loop sets it each turn so every
# recorded tool call is tagged with the round (model call) it happened in


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

        # Wrap the tool so every invocation is recorded in call order. This
        # captures all locally-executed tools uniformly — including the
        # tools that skills register, since they're decorated the same way.
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            bound = sig.bind(*args, **kwargs)
            TOOL_CALLS.append({"round": CURRENT_ROUND, "tool": func.__name__, "args": dict(bound.arguments)})
            return func(*args, **kwargs)

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


# --- 5. The five working tools (unchanged from Eps 2-4).
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
            content = f.read_text(encoding="utf-8", errors="replace")
            for i, line in enumerate(content.splitlines(), 1):
                if regex.search(line):
                    rel = f.relative_to(SANDBOX.resolve())
                    results.append(f"{rel}:{i}: {line[:200]}")
                    if len(results) >= 50:
                        return "\n".join(results) + "\n... (truncated at 50 matches)"
        except Exception:
            continue
    return "\n".join(results) if results else f"No matches for {pattern!r}."


# --- 6. The planning tool (Ep 4, unchanged).
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


# --- 7. Skills system (NEW for Ep 5).
LOADED_SKILLS: dict[str, dict] = {}   # name -> {"description", "tools", "body"}
_SKILLS_DIR = SANDBOX / ".skills"


def _parse_skill_md(path: Path) -> dict:
    """Tiny YAML frontmatter parser — no external deps.

    Returns a dict with at least: name, description, tools (list), body.
    Falls back gracefully if frontmatter is missing or malformed.
    """
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    meta = {
        "name": path.parent.name,
        "description": "",
        "tools": [],
        "body": text.strip(),
    }
    if not lines or lines[0].strip() != "---":
        return meta
    try:
        end = lines.index("---", 1)
    except ValueError:
        return meta
    fm_lines = lines[1:end]
    body = "\n".join(lines[end + 1:]).strip()
    meta["body"] = body
    for line in fm_lines:
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k = k.strip()
        v = v.strip()
        if k == "tools":
            if v.startswith("[") and v.endswith("]"):
                meta["tools"] = [x.strip() for x in v[1:-1].split(",") if x.strip()]
        elif k in ("name", "description"):
            meta[k] = v
    return meta


@tool(
    "List available skills (name + description for each). Skills are bundles "
    "of procedural knowledge and tools you can load on demand when their "
    "description matches your current task. Call this when starting a task "
    "to see what's available, or whenever you find yourself unsure how to "
    "proceed. Cheap — only metadata is returned, not the skill bodies."
)
def list_skills() -> str:
    if not _SKILLS_DIR.exists():
        return "No skills directory at .skills/."
    entries = []
    for skill_dir in sorted(_SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir():
            continue
        meta_path = skill_dir / "SKILL.md"
        if not meta_path.exists():
            continue
        meta = _parse_skill_md(meta_path)
        loaded = " (LOADED)" if meta["name"] in LOADED_SKILLS else ""
        entries.append(f"- **{meta['name']}**{loaded}: {meta['description']}")
    if not entries:
        return "No skills available."
    return "Available skills:\n" + "\n".join(entries)


@tool(
    "Load a skill's full body of instructions and register any tools it "
    "provides. Call this when a skill's description matches your task. "
    "The skill's body becomes part of your system prompt; its tools become "
    "available immediately and stay loaded for the rest of the run. "
    "Idempotent — loading twice is a no-op."
)
def load_skill(name: str) -> str:
    if name in LOADED_SKILLS:
        return f"Skill '{name}' is already loaded."
    meta_path = _SKILLS_DIR / name / "SKILL.md"
    if not meta_path.exists():
        return (
            f"Error: skill '{name}' not found. "
            f"Call list_skills() to see available skills."
        )
    skill = _parse_skill_md(meta_path)
    LOADED_SKILLS[name] = skill
    new_tools = []
    for tool_name in skill["tools"]:
        if tool_name in _SKILL_TOOLS_REGISTRY:
            TOOLS_BY_NAME[tool_name] = _SKILL_TOOLS_REGISTRY[tool_name]
            new_tools.append(tool_name)
    return (
        f"Skill '{name}' loaded. Tools registered: {new_tools or 'none'}.\n\n"
        f"=== {name.upper()} ===\n{skill['body']}"
    )


# --- 8. Skill-provided tool implementations.

# web_search is implemented as an Anthropic SERVER tool — the API itself
# performs the search and inlines the result. Our Python stub here exists
# only so load_skill can register it in TOOLS_BY_NAME for symmetry; it's
# never actually dispatched locally (the model's tool_use for web_search
# comes back already-resolved as a server_tool_use + web_search_tool_result
# pair, which our agent loop ignores for dispatch). The CONDITIONAL inclusion
# of the server-tool entry in the tools= list is handled in _tools_for_api()
# below — keyed on `"research" in LOADED_SKILLS`.
def web_search(*args, **kwargs) -> str:
    return "[web_search is handled server-side; this local stub should not be invoked]"


@tool(
    "Fetch the contents of a URL as text. Returns the response body "
    "(decoded as UTF-8, errors replaced). Useful when you have a "
    "specific URL to read (typically after web_search returns one). "
    "Provided by the `research` skill."
)
def fetch_url(url: str) -> str:
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "md2html-agent/1.0"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
            body = resp.read()
        text = body.decode("utf-8", errors="replace")
        if len(text) > 50_000:
            return text[:50_000] + f"\n\n[...truncated; full length was {len(text):,} chars]"
        return text
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code} fetching {url}: {e.reason}"
    except urllib.error.URLError as e:
        return f"URL error fetching {url}: {e.reason}"
    except Exception as e:
        return f"Error fetching {url}: {type(e).__name__}: {e}"


@tool(
    "Run a linter (ruff) over the sandbox. Returns the lint output, or "
    "'clean' if there are no issues. Provided by the `verification` skill."
)
def lint(path: str = ".") -> str:
    p = _safe_path(path)
    result = subprocess.run(  # noqa: S603  # nosec
        ["ruff", "check", str(p)],
        capture_output=True, text=True,
        cwd=SANDBOX, timeout=30,
        encoding="utf-8", errors="replace",
        check=False,
    )
    out = (result.stdout + result.stderr).strip()
    if not out:
        return "clean"
    return out


@tool(
    "Run pytest with coverage reporting. Returns the coverage summary. "
    "Useful for verifying new code is covered by tests. Provided by the "
    "`verification` skill."
)
def coverage() -> str:
    result = subprocess.run(  # noqa: S603  # nosec
        ["python", "-m", "pytest", "--cov=md2html", "--cov-report=term-missing", "-q"],
        capture_output=True, text=True,
        cwd=SANDBOX, timeout=60,
        encoding="utf-8", errors="replace",
        check=False,
    )
    return (result.stdout + result.stderr).strip() or "(no output)"


# Registry of tools that ONLY register when their owning skill is loaded.
_SKILL_TOOLS_REGISTRY: dict[str, Callable] = {
    "web_search": web_search,   # stub — server-tool handled in _tools_for_api
    "fetch_url": fetch_url,
    "lint": lint,
    "coverage": coverage,
}


# --- 9. Tool registry (base, before any skills load).
BASE_TOOLS = [bash, read, write, edit, grep, done, write_plan, think,
              list_skills, load_skill]
TOOLS_BY_NAME: dict[str, Callable] = {t.__name__: t for t in BASE_TOOLS}


# --- 10. Cache-control helpers (Anthropic prompt caching).
def _system_with_dynamic():
    """System prompt = stable base (cached) + dynamic blocks (plan, skills).

    Dynamic blocks live AFTER the cached base so the base stays cached
    across all iterations. Each dynamic block is its own text block and
    is NOT cached — when CURRENT_PLAN or LOADED_SKILLS change, only the
    dynamic blocks need to be re-sent, the base stays warm.

    This is the same mechanism Ep 4 introduced for the plan; Ep 5 just
    extends it to also carry loaded-skill bodies.
    """
    base = {"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}
    blocks = [base]
    if CURRENT_PLAN:
        blocks.append({
            "type": "text",
            "text": f"\n\n[CURRENT PLAN]\n{_format_plan(CURRENT_PLAN)}\n[end plan]",
        })
    for name, skill in LOADED_SKILLS.items():
        blocks.append({
            "type": "text",
            "text": f"\n\n[LOADED SKILL: {name}]\n{skill['body']}\n[end skill: {name}]",
        })
    return blocks


def _tools_for_api():
    """Build the tools list for the API call.

    Regular tools come from TOOLS_BY_NAME (which load_skill mutates). The
    last regular tool gets cache_control so the regular-tools prefix is
    cached. The Anthropic server-side web_search tool is appended AFTER
    if and only if the `research` skill is loaded — it's not cached
    (small entry, appended after the cache marker).
    """
    out = [fn.tool_definition for fn in TOOLS_BY_NAME.values()
           if hasattr(fn, "tool_definition")]
    if out:
        out[-1] = {**out[-1], "cache_control": {"type": "ephemeral"}}
    if "research" in LOADED_SKILLS:
        out.append({
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": WEB_SEARCH_MAX_USES,
        })
    return out


# --- 11. Compaction (unchanged shape from Eps 3-4).
SUMMARIZER_PROMPT = (
    "You're summarizing an in-progress coding-agent transcript so the agent can keep "
    "working with less context. Produce a concise structured summary that captures: "
    "(1) the user's original task, (2) what's been investigated so far (files read, "
    "what was found), (3) what's been changed so far (files written, edits applied), "
    "(4) what's still to do, (5) any errors encountered and how they were handled, "
    "(6) which skills (if any) have been loaded and what they're for. "
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
    return " ".join(
        b.get("text", "") for b in content
        if isinstance(b, dict) and b.get("type") == "text"
    )


def compact(messages):
    asst_positions = [i for i, m in enumerate(messages) if m.get("role") == "assistant"]
    if len(asst_positions) <= KEEP_LAST_ITERATIONS:
        return messages, False, 0, 0
    head = messages[:1]
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
    su = summary_resp.usage
    return head + [summary_msg] + tail, True, su.input_tokens, su.output_tokens


# --- 12. Block-to-dict helper for persisting assistant messages.
def _block_to_dict(b):
    if b.type == "text":
        return {"type": "text", "text": b.text}
    if b.type == "tool_use":
        return {"type": "tool_use", "id": b.id, "name": b.name, "input": b.input}
    # Server-tool blocks (server_tool_use, web_search_tool_result, etc.)
    # fall through to pydantic dump — needed for context preservation.
    return b.model_dump()


def _preview_args(d) -> str:
    """Render a tool's input dict as a short, log-friendly preview string.

    Short values are shown inline; long values are summarized by length.
    """
    parts = []
    for k, v in (d or {}).items():
        if len(repr(v)) < 60:
            parts.append(f"{k}={v!r}")
        else:
            parts.append(f"{k}=<{len(str(v))} chars>")
    return ", ".join(parts)


def write_tool_telemetry():
    """Write the tool calls made this run to tool_calls.jsonl, one JSON object
    per line in call order. Recording only — rendering a summary is left to
    whatever reads the file."""
    with open("tool_calls.jsonl", "w", encoding="utf-8") as f:
        for call in TOOL_CALLS:
            f.write(json.dumps(call) + "\n")


def write_metrics():
    """Write this run's token usage to metrics.json. Recording only — the
    harness (run.py) reads this and renders the summary. Records cache,
    compaction, reasoning, skills, and server-tool usage so the harness can
    show each section; per_iter carries [in, out, cache_w, cache_r]."""
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
            "skills": {
                "list_skills": list_skills_calls,
                "load_skill": load_skill_calls,
                "loaded": loaded_skill_names,
            },
            "server_tool_calls": dict(server_tool_calls),
            "per_iter": per_iter,
        }],
        "inputs": {"system": SYSTEM, "task": TASK},
        "config": {
            "MODEL": MODEL,
            "COMPACTION_THRESHOLD": COMPACTION_THRESHOLD,
            "KEEP_LAST_ITERATIONS": KEEP_LAST_ITERATIONS,
            "MAX_ITERATIONS": MAX_ITERATIONS,
            "WEB_SEARCH_MAX_USES": WEB_SEARCH_MAX_USES,
        },
    }
    with open("metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)


# --- 13. The agent loop.
SYSTEM = (
    "You are a coding assistant operating inside a sandboxed working "
    "directory. Use the available tools to investigate, modify, and "
    "verify code. Ground claims in what you actually observe; don't "
    "guess. When the task is complete, call done() with a clear summary "
    "of what you did."
)

TASK = """I want to add support for GitHub-flavored alerts to md2html.
They look like this:

    > [!NOTE]
    > Useful information that users should know.

    > [!WARNING]
    > Urgent info that needs immediate attention.

**IMPORTANT — read carefully:**
The test fixture at tests/fixtures/github_alerts.html may be WRONG —
I wrote it from memory and I'm not confident about the exact class
names. GitHub's actual docs are the ground truth, NOT the fixture.

You MUST use web_search to look up GitHub's latest docs FIRST to
confirm the exact class names and HTML structure. If your
implementation matches the fixture but doesn't match what GitHub
actually emits, the work is incorrect even if pytest passes. If the
docs contradict the fixture, fix the fixture to match the docs.

THEN implement the extension as a new file under md2html/extensions/.
Keep your diff minimal — don't refactor unrelated parts of the
codebase. All existing tests must still pass."""

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
list_skills_calls = 0
load_skill_calls = 0
loaded_skill_names: list[str] = []
# Server-side tool counters (e.g., Anthropic's web_search). These show up as
# `server_tool_use` blocks in resp.content — distinct from regular `tool_use`
# blocks the agent loop dispatches. Without explicit counting, server-tool
# usage is invisible in the metrics.
server_tool_calls: dict[str, int] = {}
per_iter = []

try:
    while iteration < MAX_ITERATIONS:
        iteration += 1
        CURRENT_ROUND = iteration   # tag tool calls with the round they happen in

        resp = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=_system_with_dynamic(),
            tools=_tools_for_api(),
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

        # Persist the assistant turn (including any server_tool_use /
        # web_search_tool_result blocks — they're needed for context).
        assistant_blocks = [_block_to_dict(b) for b in resp.content]
        messages.append({"role": "assistant", "content": assistant_blocks})

        # Only LOCAL tool_use blocks need dispatch. Server tools are
        # already resolved by Anthropic; they appear as server_tool_use
        # alongside their *_tool_result blocks in the same response.
        tool_uses = [b for b in resp.content if b.type == "tool_use"]

        # Surface server-tool invocations (web_search, etc.) for visibility
        # and counting. Result blocks (web_search_tool_result) are NOT looped
        # — they're already attached to the assistant turn we persisted above
        # via _block_to_dict's pydantic-dump fallback.
        for stu in resp.content:
            if stu.type == "server_tool_use":
                arg_preview = _preview_args(stu.input)
                print(f"> [server] {stu.name}({arg_preview})")
                server_tool_calls[stu.name] = server_tool_calls.get(stu.name, 0) + 1

        # A turn that contains ONLY server_tool_use (no local tool_use, no
        # done()) still needs to continue the loop — Anthropic has already
        # appended the *_tool_result; the model will see it on the next call
        # and respond with either more tool calls or done(). Only break when
        # the model produces a turn with NO tool activity at all.
        any_tool_activity = tool_uses or any(
            b.type == "server_tool_use" for b in resp.content
        )

        if not any_tool_activity:
            text = "".join(b.text for b in resp.content if b.type == "text")
            print(f"\n=== FINAL RESPONSE (no done tool called) ===\n\n{text}")
            break

        tool_results = []
        for tu in tool_uses:
            try:
                fn = TOOLS_BY_NAME[tu.name]
                args = tu.input or {}
                arg_preview = _preview_args(args)
                print(f"> {tu.name}({arg_preview})")
                result = fn(**args)
                if tu.name == "write_plan":
                    plan_writes += 1
                elif tu.name == "think":
                    think_calls += 1
                elif tu.name == "list_skills":
                    list_skills_calls += 1
                elif tu.name == "load_skill":
                    load_skill_calls += 1
                    # Track which skill was actually loaded (skill name is in args).
                    sname = args.get("name")
                    if sname and sname in LOADED_SKILLS and sname not in loaded_skill_names:
                        loaded_skill_names.append(sname)
            except (TypeError, KeyError, ValueError) as e:
                result = f"Error executing {tu.name}: {type(e).__name__}: {e}"
                print(f"  ! {result}")
            preview = result if len(result) < 5000 else result[:5000] + "...[truncated]"
            print(f"  {preview}\n")
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tu.id,
                "content": result,
            })
        messages.append({"role": "user", "content": tool_results})

        # Compaction check — same effective-tokens calc as Ep 4.
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
