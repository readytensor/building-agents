"""
Episode 6 — Orchestration

Adds a `delegate` tool + worker runtime to Ep 5. The orchestrator (top-level
agent) has no codebase-mutation tools; it can only call `delegate` to spawn
worker agents who do the actual work. Multiple `delegate` tool_uses in one
assistant turn run CONCURRENTLY (ThreadPoolExecutor).

New additions on top of Ep 5:

1. `run_agent(task, agent_type) -> str` — Ep 5's main loop, refactored
   into a function. Used recursively: the orchestrator is `run_agent(TASK,
   "orchestrator")`; each worker is `run_agent(subtask, agent_type)`. ALL
   formerly-module-level mutable state (plan, loaded_skills, tools_by_name,
   messages, token counters) is now per-call function-local — reentrant.

2. `delegate(task, agent_type)` tool — calls `run_agent` recursively.
   Available only to the orchestrator (not in any worker's toolset).

3. Parallel dispatcher — when an assistant turn contains multiple `delegate`
   tool_uses, they fan out through a ThreadPoolExecutor. Mirrors Anthropic's
   own pattern (Claude Code subagents, Agent SDK subagents).

4. `.agents/<name>.md` worker configs — YAML frontmatter + body, mirroring
   `.skills/<name>/SKILL.md`. Parsed at agent.py import time into
   AGENT_CONFIGS. Two configs ship in `initial/.agents/`: implementer +
   verifier.

5. Per-worker logging prefix (`[orch]`, `[w1-implementer]`, …) so the
   parallel transcript is readable. Wrapped under a Lock so prefixed
   lines don't interleave.

Everything else inherited from Ep 5: skills system, planning + think,
5 working tools, done, compaction, sandbox reset.

NOTE — DEV-TIME SDK SWAP (2026-05-25):
Continues Eps 4/5's pattern — native Anthropic SDK + prompt caching during
development. Translate to openai SDK when shipping; drop cache_control.
"""
import inspect
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
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
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
MAX_TOKENS = int(os.environ.get("ANTHROPIC_MAX_TOKENS", 4096))

# --- Knobs.
COMPACTION_THRESHOLD = int(os.environ.get("EP3_THRESHOLD", 30_000))
KEEP_LAST_ITERATIONS = int(os.environ.get("EP3_KEEP", 4))
MAX_ITERATIONS = int(os.environ.get("EP5_MAX_ITER", 200))
MAX_WORKER_ITER = int(os.environ.get("EP6_MAX_WORKER_ITER", 60))
WEB_SEARCH_MAX_USES = int(os.environ.get("EP5_WEB_SEARCH_MAX", 10))

# --- Thread-safe printing with per-worker label.
_PRINT_LOCK = threading.Lock()
_WORKER_COUNTER = itertools.count(1)


def _print(label: str, text: str) -> None:
    """Print under lock with a worker-id prefix. Each call writes one atomic
    block (so parallel workers don't interleave mid-line). The label format
    is '[orch]' for the orchestrator and '[wN-<agent_type>]' for workers."""
    with _PRINT_LOCK:
        for line in text.splitlines() or [""]:
            print(f"[{label}] {line}", flush=True)


def _preview_args(args: dict) -> str:
    """Render a tool call's args for the transcript: each value inline if its
    repr is short, otherwise summarized as a char count."""
    parts = []
    for k, v in (args or {}).items():
        if len(repr(v)) < 60:
            parts.append(f"{k}={v!r}")
        else:
            parts.append(f"{k}=<{len(str(v))} chars>")
    return ", ".join(parts)


def _truncate(text: str, limit: int = 400) -> str:
    """Truncate a tool-result string for transcript display."""
    if len(text) < limit:
        return text
    return text[:limit] + "...[truncated]"


# --- 3. The @tool decorator (Anthropic shape, unchanged from Ep 5).
def tool(description: str):
    json_types = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        list: "array",
        dict: "object",
    }

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
            "name": func.__name__,
            "description": description,
            "input_schema": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }
        return func
    return decorator


# --- 4. The done tool.
class TaskComplete(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


@tool("Signal that the task is complete. Pass a clear summary of what you did.")
def done(message: str) -> str:
    raise TaskComplete(message)


# --- 5. The five working tools (unchanged from Eps 2-5).
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
    numbered = [f"{i+1:5d}\t{line}" for i, line in enumerate(lines)]
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
            file_lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
            for i, line in enumerate(file_lines, 1):
                if regex.search(line):
                    rel = f.relative_to(SANDBOX)
                    results.append(f"{rel}:{i}: {line[:200]}")
                    if len(results) >= 50:
                        return "\n".join(results) + "\n... (truncated at 50 matches)"
        except Exception:
            continue
    return "\n".join(results) if results else f"No matches for {pattern!r}."


# --- 6. Skill-provided tool implementations (unchanged from Ep 5).
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
        req = urllib.request.Request(url, headers={"User-Agent": "ep06-agent/1.0"})
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


@tool("Run a linter (ruff) over the sandbox. Returns the lint output, or 'clean' if there are no issues. Provided by the `verification` skill.")
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
    return out or "clean"


@tool("Run pytest with coverage reporting. Returns the coverage summary. Provided by the `verification` skill.")
def coverage() -> str:
    result = subprocess.run(  # noqa: S603  # nosec
        ["python", "-m", "pytest", "--cov=md2html", "--cov-report=term-missing", "-q"],
        capture_output=True, text=True,
        cwd=SANDBOX, timeout=60,
        encoding="utf-8", errors="replace",
        check=False,
    )
    return (result.stdout + result.stderr).strip() or "(no output)"


# --- 7. Planning + think tools (unchanged from Ep 5; state is per-call).
@tool(
    "Set or update your working plan for a MULTI-STEP TASK. Pass the FULL "
    "current state of the plan as a list of steps. Each step can be either "
    "(a) a string describing the step, or (b) a dict with 'content' (string) "
    "and 'status' (one of 'pending', 'in_progress', 'completed')."
)
def write_plan(steps) -> str:
    # The actual plan list lives in run_agent's function locals; this tool's
    # body is invoked via a closure that captures the per-call plan. See
    # `_make_plan_tool` below. This module-level function exists only so
    # its @tool decorator can publish a tool_definition for schema purposes.
    raise RuntimeError("write_plan should be dispatched via per-call closure")


@tool(
    "Externalize your reasoning about a hard problem or decision. Pass a "
    "thought as a string; it is echoed back unchanged."
)
def think(thought: str) -> str:
    return thought


def _format_plan(plan: list[dict]) -> str:
    if not plan:
        return "(no plan set)"
    icons = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]"}
    lines = []
    for i, step in enumerate(plan, 1):
        icon = icons.get(step.get("status", "pending"), "[?]")
        lines.append(f"  {i}. {icon} {step.get('content', '')}")
    return "\n".join(lines)


def _make_plan_tool(plan: list[dict]) -> Callable:
    """Return a closure that mutates the per-call plan list. Carries the
    schema from the module-level write_plan stub."""
    def _plan_impl(steps) -> str:
        if isinstance(steps, str):
            try:
                steps = json.loads(steps)
            except Exception:
                return "Error: `steps` must be a list of steps, not a single string."
        if not isinstance(steps, list):
            return f"Error: `steps` must be a list, got {type(steps).__name__}."
        plan.clear()
        for step in steps:
            if isinstance(step, str):
                plan.append({"content": step, "status": "pending"})
            elif isinstance(step, dict):
                plan.append({
                    "content": str(step.get("content", "")),
                    "status": step.get("status", "pending"),
                })
        return f"Plan updated ({len(plan)} steps):\n{_format_plan(plan)}"
    _plan_impl.tool_definition = write_plan.tool_definition
    return _plan_impl


# --- 8. Skills system (lifted from Ep 5; loaded_skills is now per-call).
_SKILLS_DIR = SANDBOX / ".skills"


def _parse_yaml_frontmatter(path: Path) -> tuple[dict, str]:
    """Parse `---`-delimited YAML frontmatter at the top of a markdown file.
    Returns (frontmatter_dict, body). Tiny parser — no external deps. Used
    for both .skills/ and .agents/."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text.strip()
    try:
        end = lines.index("---", 1)
    except ValueError:
        return {}, text.strip()
    body = "\n".join(lines[end + 1:]).strip()
    fm: dict = {}
    current_key: str | None = None
    for line in lines[1:end]:
        if not line.strip():
            continue
        if line[0] in " \t" and current_key:
            # continuation of a multi-line value
            existing = fm.get(current_key, "")
            fm[current_key] = (existing + "\n" + line.strip()).strip()
            continue
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k = k.strip()
        v = v.strip()
        if v.startswith("[") and v.endswith("]"):
            fm[k] = [x.strip() for x in v[1:-1].split(",") if x.strip()]
        elif v == "|" or v == ">":
            fm[k] = ""
            current_key = k
        else:
            fm[k] = v
            current_key = k
    return fm, body


def _load_skill_body(name: str) -> dict:
    """Load a skill's parsed metadata + body. Returns dict with name,
    description, tools (list), body. Used by run_agent at start to preload
    skills the agent_type requires."""
    meta_path = _SKILLS_DIR / name / "SKILL.md"
    fm, body = _parse_yaml_frontmatter(meta_path)
    return {
        "name": fm.get("name", name),
        "description": fm.get("description", ""),
        "tools": fm.get("tools", []),
        "body": body,
    }


def _make_list_skills_tool(loaded: dict) -> Callable:
    """Closure that reports skills + which are LOADED in this run."""
    @tool(
        "List available skills (name + description for each). Skills are "
        "bundles of procedural knowledge and tools you can load on demand "
        "when their description matches your current task. Cheap — only "
        "metadata is returned."
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
            fm, _ = _parse_yaml_frontmatter(meta_path)
            sname = fm.get("name", skill_dir.name)
            tag = " (LOADED)" if sname in loaded else ""
            entries.append(f"- **{sname}**{tag}: {fm.get('description', '')}")
        return ("Available skills:\n" + "\n".join(entries)) if entries else "No skills available."
    return list_skills


def _make_load_skill_tool(loaded: dict, tools_by_name: dict) -> Callable:
    """Closure that loads a skill into THIS worker's loaded_skills +
    tools_by_name dicts (per-call state, not shared across workers)."""
    @tool(
        "Load a skill's full body of instructions and register any tools it "
        "provides. Call when a skill's description matches your task. The "
        "skill's body becomes part of your system prompt; its tools become "
        "available immediately. Idempotent."
    )
    def load_skill(name: str) -> str:
        if name in loaded:
            return f"Skill '{name}' is already loaded."
        meta_path = _SKILLS_DIR / name / "SKILL.md"
        if not meta_path.exists():
            return f"Error: skill '{name}' not found. Call list_skills() to see available skills."
        skill = _load_skill_body(name)
        loaded[name] = skill
        new_tools = []
        for tool_name in skill["tools"]:
            if tool_name in _SKILL_TOOL_REGISTRY:
                tools_by_name[tool_name] = _SKILL_TOOL_REGISTRY[tool_name]
                new_tools.append(tool_name)
        return (
            f"Skill '{name}' loaded. Tools registered: {new_tools or 'none'}.\n\n"
            f"=== {name.upper()} ===\n{skill['body']}"
        )
    return load_skill


# Registry of tools that ONLY register when their owning skill is loaded.
_SKILL_TOOL_REGISTRY: dict[str, Callable] = {
    "web_search": web_search,
    "fetch_url": fetch_url,
    "lint": lint,
    "coverage": coverage,
}


# --- 9. AgentConfig + .agents/ loader (NEW for Ep 6).
@dataclass(frozen=True)
class AgentConfig:
    name: str
    description: str
    tools: tuple[str, ...]            # allowlist into TOOL_FUNCTIONS
    skills: tuple[str, ...]           # pre-loaded before first turn
    prompt: str                       # full system prompt for this agent_type


_AGENTS_DIR = SANDBOX / ".agents"


def _load_agent_configs() -> dict[str, AgentConfig]:
    out: dict[str, AgentConfig] = {}
    if not _AGENTS_DIR.exists():
        return out
    for p in sorted(_AGENTS_DIR.glob("*.md")):
        fm, body = _parse_yaml_frontmatter(p)
        name = fm.get("name") or p.stem
        out[name] = AgentConfig(
            name=name,
            description=fm.get("description", ""),
            tools=tuple(fm.get("tools", [])),
            skills=tuple(fm.get("skills", [])),
            prompt=body,
        )
    return out


# --- 10. Tool function registry (every callable known to the system).
# Each tool's @tool decorator publishes a tool_definition with its schema.
# Per-worker TOOLS_BY_NAME is a filtered subset of this dict.
TOOL_FUNCTIONS: dict[str, Callable] = {
    "bash": bash,
    "read": read,
    "write": write,
    "edit": edit,
    "grep": grep,
    "done": done,
    "think": think,
    # planning + skills are PER-CALL closures; bound in run_agent.
    # delegate is bound only in the orchestrator (see below).
    # skill-provided tools (web_search, fetch_url, lint, coverage) get
    # registered into a worker's TOOLS_BY_NAME via load_skill.
}


# --- 11. Compaction (unchanged shape from Eps 3-5; now takes messages).
SUMMARIZER_PROMPT = (
    "You're summarizing an in-progress coding-agent transcript so the agent can keep "
    "working with less context. Capture: (1) original task, (2) what's been investigated, "
    "(3) what's been changed, (4) what's still to do, (5) errors encountered, "
    "(6) skills loaded. Be terse but specific."
)


def _format_as_transcript(messages):
    out = []
    for m in messages:
        role = m.get("role", "?")
        content = m.get("content", "")
        if isinstance(content, str):
            out.append(f"{role.upper()}: {content}")
            continue
        text_parts, tool_use_lines, tool_result_lines = [], [], []
        for b in content:
            btype = b.get("type") if isinstance(b, dict) else None
            if btype == "text":
                text_parts.append(b.get("text", ""))
            elif btype == "tool_use":
                tool_use_lines.append(f"  -> {b.get('name')}({json.dumps(b.get('input'), default=str)})")
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
                tool_result_lines.append(f"TOOL RESULT: {tc if len(tc) < 500 else tc[:500] + '...[truncated]'}")
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
    return " ".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")


def _compact(messages):
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
        messages=[{"role": "user", "content": (
            f"Original task:\n{_extract_text(head[0]['content'])}\n\n"
            f"Transcript to summarize:\n{_format_as_transcript(middle)}"
        )}],
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
    new_messages = head + [summary_msg] + tail
    in_tokens = summary_resp.usage.input_tokens
    out_tokens = summary_resp.usage.output_tokens
    return new_messages, True, in_tokens, out_tokens


# --- 12. Block-to-dict helper.
def _block_to_dict(b):
    if b.type == "text":
        return {"type": "text", "text": b.text}
    if b.type == "tool_use":
        return {"type": "tool_use", "id": b.id, "name": b.name, "input": b.input}
    return b.model_dump()


# --- 13. Per-worker metrics aggregator.
@dataclass
class WorkerMetrics:
    iterations: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write: int = 0
    cache_read: int = 0
    compact_in: int = 0
    compact_out: int = 0
    compactions: int = 0
    plan_writes: int = 0
    think_calls: int = 0
    list_skills_calls: int = 0
    load_skill_calls: int = 0
    delegate_calls: int = 0
    server_tool_calls: dict = field(default_factory=dict)
    loaded_skill_names: list = field(default_factory=list)


# Top-level aggregate across all workers (orchestrator + children).
GLOBAL_METRICS: dict[str, WorkerMetrics] = {}
_METRICS_LOCK = threading.Lock()

# --- Tool-call telemetry: record every tool each agent invokes, in order,
# tagged with which agent made it (orchestrator vs each worker), so we can see
# the path the whole system took and how many calls each agent made. This
# varies run to run. Summarized and written to tool_calls.jsonl at the end.
TOOL_CALLS = []  # list of {"agent": label, "tool": name, "args": {...}}


def write_tool_telemetry():
    """Write the tool calls made this run to tool_calls.jsonl, one JSON object
    per line in call order (each tagged with the agent that made it). Recording
    only — rendering a summary is left to whatever reads the file."""
    with open("tool_calls.jsonl", "w", encoding="utf-8") as f:
        for call in TOOL_CALLS:
            f.write(json.dumps(call) + "\n")


def write_metrics():
    """Write this run's usage to metrics.json — one entry per worker (the
    orchestrator plus every delegated worker). Recording only; the harness
    (run.py) reads this and renders the per-worker + aggregate summary."""
    agents = []
    for label, m in GLOBAL_METRICS.items():
        agents.append({
            "label": label,
            "iterations": m.iterations,
            "input_tokens": m.input_tokens,
            "output_tokens": m.output_tokens,
            "cache_write": m.cache_write,
            "cache_read": m.cache_read,
            "compactions": m.compactions,
            "compact_in": m.compact_in,
            "compact_out": m.compact_out,
            "reasoning": {"write_plan": m.plan_writes, "think": m.think_calls},
            "skills": {
                "list_skills": m.list_skills_calls,
                "load_skill": m.load_skill_calls,
                "loaded": m.loaded_skill_names,
            },
            "delegate_calls": m.delegate_calls,
            "server_tool_calls": dict(m.server_tool_calls),
        })
    metrics = {
        "agents": agents,
        "inputs": {"system": ORCHESTRATOR_SYSTEM, "task": TASK},
        "config": {
            "COMPACTION_THRESHOLD": COMPACTION_THRESHOLD,
            "KEEP_LAST_ITERATIONS": KEEP_LAST_ITERATIONS,
            "MAX_ITERATIONS": MAX_ITERATIONS,
            "MAX_WORKER_ITER": MAX_WORKER_ITER,
        },
    }
    with open("metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)


# --- 14. The agent loop, refactored as a recursive function.
ORCHESTRATOR_SYSTEM = """You are an **orchestrator**.

Your job is to decompose the user's task into focused subtasks and dispatch
them to specialized worker agents via the `delegate` tool. You yourself have
NO codebase-mutation tools — you cannot read, write, edit, grep, or run
shell commands. All work happens through workers.

## How to work

1. **Discover.** Call `list_skills` to see what skills exist (workers can
   load these).

2. **Plan.** Call `write_plan` to record your decomposition. In each step,
   note whether it is **PARALLELIZABLE** (independent — can run concurrently
   with peers) or **SEQUENTIAL** (depends on a prior step's output).

3. **Dispatch in parallel WHEREVER POSSIBLE.** This is the whole point of
   orchestration. The rules:

   - When you have ≥2 independent subtasks, you **MUST issue ALL their
     `delegate` tool calls in the SAME assistant turn.** The runtime will
     dispatch them concurrently across threads and return all results in
     the next turn.
   - **DO NOT** dispatch a sequence of one-delegate-per-turn for
     independent work. If you find yourself thinking *"let me dispatch
     the first feature, see how it goes, then the second"* — STOP. Batch
     them. Single-delegate turns are reserved for steps that DEPEND on
     a prior step's output (e.g., verifier runs after implementers; a
     fix-up worker reacts to a specific failure).
   - **DO NOT** dispatch a "recon" or "exploration" worker as a first step
     to map out the codebase for you. If the user's task mentions specific
     files or paths, include those paths in the worker task strings —
     workers have `read`/`grep`/`bash` and can investigate themselves.
     A recon-first pattern serialises what could be parallel and burns
     budget on context the implementer worker is going to re-read anyway.

4. **Always verify before done().** After implementation workers finish,
   dispatch a `verifier` worker (in a separate turn — it depends on their
   outputs). Only call `done()` after the verifier reports a clean pass.

## Worker task strings

Workers see ONLY the string you pass — no inheritance from your context,
no access to your plan, no access to other workers' outputs. Each task
string MUST be SELF-CONTAINED:
- What to build (specific, scoped to that worker only)
- Where the relevant files live (paths, fixture locations)
- Success criteria for that specific worker
- Any context from prior workers' outputs that this worker needs

## Counter-patterns to actively avoid

- ❌ Dispatching one worker, reading its result, then dispatching the next
  independent worker. (Use parallel batching instead.)
- ❌ Doing "recon" via a first worker before dispatching implementers.
  (Just include paths in the implementer task strings.)
- ❌ Calling `done()` before the verifier confirms.

## Style

- Be terse in `think` and `write_plan`. Don't restate the task.
- The user sees your `done()` summary — make it a brief structured report
  of what was implemented and what verification confirmed."""


@tool(
    "Spawn a worker agent to do `task`. `agent_type` is one of the values "
    "from .agents/ (typically 'implementer' or 'verifier'). The worker "
    "starts fresh (no inherited context) with the task string you pass, "
    "plus its configured tools and pre-loaded skills. Returns the worker's "
    "done() summary, or an error string if it hit the iteration cap. "
    "Multiple `delegate` calls in ONE assistant turn run CONCURRENTLY."
)
def delegate(task: str, agent_type: str) -> str:
    if agent_type not in AGENT_CONFIGS:
        return (f"Error: unknown agent_type '{agent_type}'. "
                f"Available: {sorted(AGENT_CONFIGS.keys())}")
    return run_agent(task, agent_type)


def _tools_for_api(tools_by_name: dict, loaded_skills: dict) -> list[dict]:
    """Build the API tools list from the worker's TOOLS_BY_NAME, applying
    cache_control to the last regular tool. Server-side web_search is
    appended (uncached) iff the `research` skill is loaded."""
    out = [fn.tool_definition for fn in tools_by_name.values()
           if hasattr(fn, "tool_definition")]
    if out:
        out[-1] = {**out[-1], "cache_control": {"type": "ephemeral"}}
    if "research" in loaded_skills:
        out.append({
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": WEB_SEARCH_MAX_USES,
        })
    return out


def _system_with_dynamic(base_prompt: str, plan: list, loaded_skills: dict) -> list[dict]:
    """Stable base block (cached) + dynamic addendum blocks (plan, skills,
    NOT cached). Same caching discipline as Eps 4-5; here the base block
    is per-agent-type so workers don't share cache with each other."""
    blocks = [{"type": "text", "text": base_prompt, "cache_control": {"type": "ephemeral"}}]
    if plan:
        blocks.append({"type": "text",
                       "text": f"\n\n[CURRENT PLAN]\n{_format_plan(plan)}\n[end plan]"})
    for name, skill in loaded_skills.items():
        blocks.append({"type": "text",
                       "text": f"\n\n[LOADED SKILL: {name}]\n{skill['body']}\n[end skill: {name}]"})
    return blocks


def run_agent(task: str, agent_type: str) -> str:
    """The agent loop — used recursively. Each call has its OWN per-worker
    state (plan, loaded_skills, tools_by_name, messages, counters)."""
    cfg = AGENT_CONFIGS[agent_type]

    # Worker identity: 'orch' for the top-level orchestrator, 'wN-<type>' for
    # delegated workers. The labels make parallel stdout legible.
    is_orchestrator = (agent_type == "orchestrator")
    if is_orchestrator:
        label = "orch"
    else:
        label = f"w{next(_WORKER_COUNTER)}-{agent_type}"

    def p(text):
        _print(label, text)

    # --- Per-call state.
    plan: list[dict] = []
    loaded_skills: dict = {}
    tools_by_name: dict[str, Callable] = {}
    metrics = WorkerMetrics()
    with _METRICS_LOCK:
        GLOBAL_METRICS[label] = metrics

    # Bind base tools per agent_type's allowlist.
    for tname in cfg.tools:
        if tname in TOOL_FUNCTIONS:
            tools_by_name[tname] = TOOL_FUNCTIONS[tname]
        elif tname == "write_plan":
            tools_by_name["write_plan"] = _make_plan_tool(plan)
        elif tname == "list_skills":
            tools_by_name["list_skills"] = _make_list_skills_tool(loaded_skills)
        elif tname == "load_skill":
            tools_by_name["load_skill"] = _make_load_skill_tool(loaded_skills, tools_by_name)
        elif tname == "delegate" and is_orchestrator:
            tools_by_name["delegate"] = delegate

    # Pre-load any skills the config requests.
    for skill_name in cfg.skills:
        skill = _load_skill_body(skill_name)
        loaded_skills[skill_name] = skill
        for st in skill["tools"]:
            if st in _SKILL_TOOL_REGISTRY:
                tools_by_name[st] = _SKILL_TOOL_REGISTRY[st]
        metrics.loaded_skill_names.append(skill_name)

    messages = [{"role": "user", "content": task}]
    iter_cap = MAX_ITERATIONS if is_orchestrator else MAX_WORKER_ITER

    p(f"=== START agent_type={agent_type} iter_cap={iter_cap} ===")
    p(f"task: {task[:300]}{'...' if len(task) > 300 else ''}")

    try:
        while metrics.iterations < iter_cap:
            metrics.iterations += 1

            resp = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=_system_with_dynamic(cfg.prompt, plan, loaded_skills),
                tools=_tools_for_api(tools_by_name, loaded_skills),
                messages=messages,
                extra_body={"cache_control": {"type": "ephemeral"}},
            )
            u = resp.usage
            cw = getattr(u, "cache_creation_input_tokens", 0) or 0
            cr = getattr(u, "cache_read_input_tokens", 0) or 0
            metrics.input_tokens += u.input_tokens
            metrics.output_tokens += u.output_tokens
            metrics.cache_write += cw
            metrics.cache_read += cr

            # Persist the assistant turn (including server_tool_use / web_search_tool_result).
            assistant_blocks = [_block_to_dict(b) for b in resp.content]
            messages.append({"role": "assistant", "content": assistant_blocks})

            tool_uses = [b for b in resp.content if b.type == "tool_use"]

            # Surface server-tool invocations (web_search, etc.).
            for stu in resp.content:
                if stu.type == "server_tool_use":
                    arg_preview = _preview_args(stu.input or {})
                    p(f"> [server] {stu.name}({arg_preview})")
                    metrics.server_tool_calls[stu.name] = metrics.server_tool_calls.get(stu.name, 0) + 1

            any_tool_activity = tool_uses or any(b.type == "server_tool_use" for b in resp.content)
            if not any_tool_activity:
                text = "".join(b.text for b in resp.content if b.type == "text")
                p(f"\n=== FINAL RESPONSE (no done tool called) ===\n\n{text}")
                return f"[worker '{agent_type}' finished without calling done()]\n\n{text}"

            # --- Parallel dispatch for delegate; sequential for others.
            delegate_uses = [b for b in tool_uses if b.name == "delegate"]
            other_uses = [b for b in tool_uses if b.name != "delegate"]
            tool_results: list = [None] * len(tool_uses)  # index by tool_use order

            # Sequential dispatch first for non-delegate tools.
            for idx, tu in enumerate(tool_uses):
                if tu.name == "delegate":
                    continue
                try:
                    fn = tools_by_name[tu.name]
                    args = tu.input or {}
                    TOOL_CALLS.append({"agent": label, "tool": tu.name, "args": args})
                    arg_preview = _preview_args(args)
                    p(f"> {tu.name}({arg_preview})")
                    result = fn(**args)
                    if tu.name == "write_plan":
                        metrics.plan_writes += 1
                    elif tu.name == "think":
                        metrics.think_calls += 1
                    elif tu.name == "list_skills":
                        metrics.list_skills_calls += 1
                    elif tu.name == "load_skill":
                        metrics.load_skill_calls += 1
                except (TypeError, KeyError, ValueError) as e:
                    result = f"Error executing {tu.name}: {type(e).__name__}: {e}"
                    p(f"  ! {result}")
                preview = _truncate(result)
                p(f"  {preview}")
                tool_results[idx] = {
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": result,
                }

            # Parallel dispatch for delegate calls.
            if delegate_uses:
                metrics.delegate_calls += len(delegate_uses)
                if len(delegate_uses) == 1:
                    # Single delegate — call inline (no thread pool overhead).
                    tu = delegate_uses[0]
                    args = tu.input or {}
                    TOOL_CALLS.append({"agent": label, "tool": "delegate", "args": args})
                    p(f"> delegate(agent_type={args.get('agent_type')!r}, "
                      f"task=<{len(str(args.get('task','')))}chars>)")
                    result = delegate(**args)
                    preview = _truncate(result)
                    p(f"  {preview}")
                    idx = tool_uses.index(tu)
                    tool_results[idx] = {
                        "type": "tool_result", "tool_use_id": tu.id, "content": result,
                    }
                else:
                    # Multiple delegates — dispatch concurrently.
                    p(f">>> Dispatching {len(delegate_uses)} workers in PARALLEL: "
                      f"{[b.input.get('agent_type') for b in delegate_uses]}")
                    with ThreadPoolExecutor(max_workers=len(delegate_uses)) as pool:
                        futures = {}
                        for tu in delegate_uses:
                            args = tu.input or {}
                            TOOL_CALLS.append({"agent": label, "tool": "delegate", "args": args})
                            p(f">    [submit] delegate(agent_type={args.get('agent_type')!r}, "
                              f"task=<{len(str(args.get('task','')))}chars>)")
                            fut = pool.submit(delegate, **args)
                            futures[fut] = tu
                        for fut in as_completed(futures):
                            tu = futures[fut]
                            try:
                                result = fut.result()
                            except Exception as e:
                                result = f"Error in worker delegate: {type(e).__name__}: {e}"
                            preview = _truncate(result)
                            p(f">    [done] delegate({tu.input.get('agent_type')!r}): {preview}")
                            idx = tool_uses.index(tu)
                            tool_results[idx] = {
                                "type": "tool_result", "tool_use_id": tu.id, "content": result,
                            }
                    p(f">>> All {len(delegate_uses)} parallel workers complete.")

            messages.append({"role": "user", "content": tool_results})

            # Compaction check.
            if u.input_tokens + cr + cw > COMPACTION_THRESHOLD:
                before = len(messages)
                messages, did, ci, co = _compact(messages)
                if did:
                    metrics.compactions += 1
                    metrics.compact_in += ci
                    metrics.compact_out += co
                    p(f"  [COMPACTION FIRED — {before} messages -> {len(messages)}, "
                      f"summarizer in={ci} out={co}]")

        # Iteration cap reached without done().
        last_text = ""
        for m in reversed(messages):
            if m.get("role") == "assistant":
                last_text = _extract_text(m.get("content", ""))
                break
        return (f"[worker '{agent_type}' exceeded iteration cap "
                f"({iter_cap}) without calling done()]\n"
                f"Last assistant text: {last_text[:300]}")

    except TaskComplete as e:
        p(f"=== TASK COMPLETE (agent_type={agent_type}) ===\n{e.message}")
        return e.message


# --- 15. Build the agent registry; orchestrator is hardcoded.
AGENT_CONFIGS: dict[str, AgentConfig] = _load_agent_configs()
AGENT_CONFIGS["orchestrator"] = AgentConfig(
    name="orchestrator",
    description="(top-level orchestrator; not dispatchable via delegate)",
    tools=("list_skills", "write_plan", "think", "delegate", "done"),
    skills=(),
    prompt=ORCHESTRATOR_SYSTEM,
)


# --- 16. The task + invocation.
TASK = """I want to round out our GFM support with three more features:

  1. Strikethrough: ~~text~~ -> <del>text</del>
  2. Task lists: list items starting with `- [ ]` or `- [x]` render
     with a disabled <input type="checkbox"> prepended (checked for [x]).
  3. Autolinks: <https://example.com> -> <a href="https://example.com">https://example.com</a>

Add each as a new extension under md2html/extensions/ and register
each in md2html/extensions/__init__.py. There are test fixture pairs
at tests/fixtures/strikethrough.{md,html}, task_lists.{md,html}, and
autolinks.{md,html} — all three currently fail because the features
aren't implemented.

Make sure all existing tests still pass. Keep diffs minimal."""

print(f"USER: {TASK}\n")

try:
    final_summary = run_agent(TASK, "orchestrator")
except Exception as e:
    print(f"\n!!! TOP-LEVEL EXCEPTION: {type(e).__name__}: {e}")
    final_summary = f"(crashed: {e})"

# --- 17. Final output + metrics. The orchestrator's answer is printed here;
# the per-worker / aggregate usage summary is recorded for the harness (run.py)
# to render — same record-in-agent, report-in-run.py split as the other episodes.
print("\n" + "=" * 70)
print("=== FINAL ORCHESTRATOR SUMMARY ===")
print("=" * 70)
print(final_summary)

write_tool_telemetry()
write_metrics()
