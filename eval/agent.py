"""The reference agent under evaluation: the Episode 5 agent, parameterized.

Reuses Ep 5's modules (tools, compaction, planning, skills) unchanged by putting
the episode directory on sys.path, then adapts them for an arbitrary repo:

  - tools.SANDBOX is repointed at the instance's working copy (the file tools
    resolve every path against it), so the agent edits the real repo, not
    episodes/05-skills/sandbox.
  - skills._SKILLS_DIR is repointed at eval/skills (generalized for any repo;
    verification runs the repo's own tests rather than md2html-specific coverage).
  - Ep 5's top-level loop is reproduced here as solve(); the initial/->sandbox
    reset is dropped because the runner owns repo state.

This module talks to the LLM, so it is exercised only by an explicit smoke run,
never the automated test suite.
"""
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

_REPO_ROOT = Path(__file__).resolve().parents[1]
_EP5 = _REPO_ROOT / "episodes" / "05-skills"
sys.path.insert(0, str(_EP5))

load_dotenv(_REPO_ROOT / ".env")

import skills  # noqa: E402
import tools  # noqa: E402
from tools import write_tool_telemetry  # noqa: E402
from compaction import compact  # noqa: E402
from planning import write_plan, system_with_plan  # noqa: E402
from skills import list_skills, load_skill, system_with_skills  # noqa: E402

# Point the reused modules at eval's own skills (generalized for arbitrary
# repos). The instance repo is pointed at per call, in solve().
skills._SKILLS_DIR = _REPO_ROOT / "eval" / "skills"

MODEL = os.environ.get("LLM_AGENT_MODEL", "gpt-5-mini")
BASE_URL = os.environ.get("LLM_BASE_URL") or ""
MAX_ITERATIONS = int(os.environ.get("MAX_ITERATIONS", 200))

SYSTEM = (
    "You are a coding assistant working inside a real code repository. Use the "
    "available tools to investigate, modify, and verify code. You also have "
    "skills you can load on demand: call list_skills() to see them, and "
    "load_skill(name) when one matches your task. If you need a capability you "
    "don't have, check list_skills first. Ground claims in what you actually "
    "observe; don't guess. When the task is complete, stop calling tools and "
    "produce a clear summary of what you did."
)


def _client(base_url):
    def api_key_for(url):
        by_provider = {"anthropic": "ANTHROPIC_API_KEY", "openrouter": "OPENROUTER_API_KEY",
                       "groq": "GROQ_API_KEY", "googleapis": "GOOGLE_API_KEY", "manus": "MANUS_API_KEY"}
        for fragment, key_var in by_provider.items():
            if fragment in url:
                return os.environ.get(key_var)
        return os.environ.get("OPENAI_API_KEY")
    return OpenAI(api_key=api_key_for(base_url), base_url=base_url or None)


def solve(repo_dir: Path, problem_statement: str) -> str:
    """Run the Ep 5 agent over repo_dir with problem_statement as the task.
    Edits repo_dir in place and returns "" — the runner captures the diff from
    the repo's git state, keeping diff capture in one place."""
    # Reset per-run skill state and repoint the file tools at this instance's
    # working copy for the whole run.
    skills.LOADED_SKILLS.clear()
    skills.LOADED_TOOLS.clear()
    tools.SANDBOX = Path(repo_dir).resolve()

    client = _client(BASE_URL)
    base_tools = tools.TOOLS + [write_plan, list_skills, load_skill]
    base_by_name = {t.__name__: t for t in base_tools}

    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": problem_statement},
    ]
    iteration = 0
    while iteration < MAX_ITERATIONS:
        iteration += 1
        tools.CURRENT_ROUND = iteration
        messages[0] = {"role": "system", "content": system_with_skills(system_with_plan(SYSTEM))}
        by_name = {**base_by_name, **skills.LOADED_TOOLS}
        tool_defs = [fn.tool_definition for fn in by_name.values()]

        resp = client.chat.completions.create(model=MODEL, messages=messages, tools=tool_defs)
        msg = resp.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))
        if not msg.tool_calls:
            break
        for tc in msg.tool_calls:
            try:
                fn = by_name[tc.function.name]
                result = fn(**json.loads(tc.function.arguments))
            except (TypeError, KeyError, json.JSONDecodeError, ValueError) as e:
                result = f"Error executing {tc.function.name}: {type(e).__name__}: {e}"
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
        messages, *_ = compact(messages, client, MODEL)

    write_tool_telemetry()
    return ""  # the runner captures the diff from the repo's git state
