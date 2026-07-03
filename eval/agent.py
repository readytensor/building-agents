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
from tools import tool, write_tool_telemetry  # noqa: E402
from compaction import compact  # noqa: E402
from planning import write_plan, system_with_plan  # noqa: E402
from skills import list_skills, load_skill, system_with_skills  # noqa: E402

from eval import container  # noqa: E402

# Point the reused modules at eval's own skills (generalized for arbitrary
# repos). The instance repo is pointed at per call, in solve().
skills._SKILLS_DIR = _REPO_ROOT / "eval" / "skills"

# Eval runs have their own model config so the shared LLM_* vars can keep
# driving the episodes. Precedence: EVAL_LLM_* (from .env or inline) falls back
# to the episodes' LLM_* if unset.
MODEL = os.environ.get("EVAL_LLM_AGENT_MODEL") or os.environ.get("LLM_AGENT_MODEL", "gpt-5-mini")
BASE_URL = os.environ.get("EVAL_LLM_BASE_URL") or os.environ.get("LLM_BASE_URL") or ""
MAX_ITERATIONS = int(os.environ.get("MAX_ITERATIONS", 200))

SYSTEM = """You are a coding assistant working inside a real code repository. \
Use the available tools to investigate, modify, and verify code.

## Skills
- Call list_skills() when you start a task, and load_skill(name) for any skill \
whose description matches the work.
- If you need a capability you don't currently have, check list_skills first \
rather than assuming you can't do it.

## Verification: REQUIRED whenever you change code
- If your task involved modifying the codebase, you MUST run the project's own \
test suite with its own runner before your final answer. Scope it to the \
relevant test files if the full suite is slow.
- If your task did NOT change code (exploring, answering questions, writing \
documentation), do not run the test suite unless the task asks for it.
- Tests or reproduction scripts you write yourself are fine to use while \
working, but they are not a substitute for the project's existing suite: the \
suite catches regressions you didn't think of.
- The project's existing tests are a regression contract: do NOT modify or \
delete them. Adding new tests is fine and encouraged. If an existing test \
fails after your change, that is evidence your change altered existing \
behavior; fix your change, not the test.
- If tests fail, fix the cause and run them again. Do not stop while tests you \
could have run remain unrun.
- If the environment truly prevents running the tests, say so explicitly in \
your final summary.

## Final change hygiene
- Prefer the smallest edit that fixes the issue over rewriting working code.
- Delete any scratch files or notes you created, so only the intended change remains.

Ground claims in what you actually observe; don't guess. When the task is \
complete, stop calling tools and produce a clear summary of what you did."""


# Ep 5's bash runs on the host. For SWE-bench instances the runner starts the
# instance's own Docker container (its real interpreter + frozen deps) and this
# proxy sends commands there instead -- so the agent can actually run the
# repo's test suite and get feedback on its edits. With no container active
# (e.g. the local md2html provider), it falls through to the host bash.
# tools.bash is the @tool-wrapped version; __wrapped__ is the original function
# (calling the wrapped one here would record each call in the telemetry twice).
_host_bash = tools.bash.__wrapped__


@tool("Execute a shell command in the repository's own environment and return "
      "its output. Use this to explore the project and to run its test suite "
      "to verify your changes.")
def bash(command: str) -> str:
    if container.ACTIVE:
        return container.exec_bash(container.ACTIVE, command)
    return _host_bash(command)


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
    # Reset per-run state and repoint the file tools at this instance's working
    # copy for the whole run. The episodes never reset TOOL_CALLS (one run per
    # process), but a multi-sample batch runs several solves in one process --
    # without the clear, each sample's tool_calls.jsonl would accumulate every
    # earlier sample's calls.
    skills.LOADED_SKILLS.clear()
    skills.LOADED_TOOLS.clear()
    tools.TOOL_CALLS.clear()
    tools.SANDBOX = Path(repo_dir).resolve()

    client = _client(BASE_URL)
    # Ep 5's toolset, with its host-only bash swapped for the container-aware
    # proxy above (same name, same schema shape -- the model sees no difference).
    file_tools = [bash if t.__name__ == "bash" else t for t in tools.TOOLS]
    base_tools = file_tools + [write_plan, list_skills, load_skill]
    base_by_name = {t.__name__: t for t in base_tools}

    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": problem_statement},
    ]
    iteration = 0
    total_in = total_out = 0
    compactions = compact_in = compact_out = 0
    tool_call_count = 0
    mechanism_calls = {"write_plan": 0, "list_skills": 0, "load_skill": 0}
    while iteration < MAX_ITERATIONS:
        iteration += 1
        tools.CURRENT_ROUND = iteration
        messages[0] = {"role": "system", "content": system_with_skills(system_with_plan(SYSTEM))}
        by_name = {**base_by_name, **skills.LOADED_TOOLS}
        tool_defs = [fn.tool_definition for fn in by_name.values()]

        resp = client.chat.completions.create(model=MODEL, messages=messages, tools=tool_defs)
        # Some providers (notably OpenRouter's free tiers) omit usage on some
        # responses; count what's reported rather than crashing the run.
        if resp.usage is not None:
            total_in += resp.usage.prompt_tokens
            total_out += resp.usage.completion_tokens
        msg = resp.choices[0].message
        messages.append(msg.model_dump(exclude_none=True))
        if not msg.tool_calls:
            break
        tool_call_count += len(msg.tool_calls)
        for tc in msg.tool_calls:
            if tc.function.name in mechanism_calls:
                mechanism_calls[tc.function.name] += 1
            try:
                fn = by_name[tc.function.name]
                args = json.loads(tc.function.arguments)
                # Live progress: one short line per tool call, so a background
                # run can be followed with tail -f on its log.
                preview = ", ".join(
                    f"{k}={v!r}" if len(repr(v)) < 60 else f"{k}=<{len(str(v))} chars>"
                    for k, v in args.items()
                )
                print(f"[iter {iteration}] {tc.function.name}({preview})", flush=True)
                result = fn(**args)
            except (TypeError, KeyError, json.JSONDecodeError, ValueError) as e:
                result = f"Error executing {tc.function.name}: {type(e).__name__}: {e}"
                print(f"[iter {iteration}] ! {result}", flush=True)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
        messages, did, ci, co, _ = compact(messages, client, MODEL)
        if did:
            compactions += 1
            compact_in += ci
            compact_out += co
            print(f"[iter {iteration}] [compaction fired: summarizer in={ci} out={co}]", flush=True)

    write_tool_telemetry()
    # Same recording split as the episodes: the agent writes raw counters, the
    # harness owns collection/reporting. The runner moves this into the batch dir.
    metrics = {
        "agents": [{
            "label": "agent",
            "iterations": iteration,
            "input_tokens": total_in,
            "output_tokens": total_out,
            "tool_calls": tool_call_count,
            "compactions": compactions,
            "compact_in": compact_in,
            "compact_out": compact_out,
            "reasoning": {"write_plan": mechanism_calls["write_plan"]},
            "skills": {
                "list_skills": mechanism_calls["list_skills"],
                "load_skill": mechanism_calls["load_skill"],
                "loaded": list(skills.LOADED_SKILLS),
            },
        }],
        "config": {"MODEL": MODEL, "MAX_ITERATIONS": MAX_ITERATIONS},
    }
    with open("metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)
    return ""  # the runner captures the diff from the repo's git state
