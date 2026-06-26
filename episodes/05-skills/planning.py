"""
Episode 5 — Skills (planning, carried forward from Ep 4)

Ep 4's contribution, carried forward unchanged: two tools plus the
dynamic system-prompt mechanism that ties them in. Ep 5's skill system
builds directly on this mechanism — loaded-skill bodies ride into the
system prompt the same way the plan does (see skills.system_with_skills).

1. write_plan(steps) — a Claude Code TodoWrite-style structured plan that lives
   in agent *state* (the CURRENT_PLAN global), not in message history. Each
   iteration the loop rebuilds the system prompt with the current plan appended
   (see system_with_plan), so the plan is always in front of the model and —
   because it lives in state, not messages — survives compaction untouched.

2. think(thought) — a no-op tool that echoes the thought back. Forcing the
   model to write the thought out is the whole point: it externalizes reasoning
   before action.

The two tools have distinct jobs (see their descriptions). Keeping them, the
plan state, and the system-prompt builder together here mirrors how Ep 3 kept
its new mechanism in compaction.py: the episode's addition is legible in one
file, and tools.py / compaction.py / agent.py stay as they were.

Imports one-way from tools (`planning → tools`, for the @tool decorator), like
agent.py imports from both. agent.py owns the base SYSTEM string and calls
system_with_plan() each turn.

See ../../README.md for context.
"""
import json

from tools import tool

# The plan lives in agent state, not message history — so it survives
# compaction and is re-injected fresh into the system prompt on every LLM call.
CURRENT_PLAN: list[dict] = []


def format_plan(plan: list[dict]) -> str:
    if not plan:
        return "(no plan set)"
    lines = []
    icons = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]"}
    for i, step in enumerate(plan, 1):
        icon = icons.get(step.get("status", "pending"), "[?]")
        content = step.get("content", "")
        lines.append(f"  {i}. {icon} {content}")
    return "\n".join(lines)


def system_with_plan(base_system: str) -> str:
    """The dynamic system prompt: the stable base plus the current plan appended.
    The loop calls this each iteration and sets messages[0] to the result, so the
    plan is always visible and the prefix stays stable when the plan is unchanged.
    With no plan set, this is just the base system prompt."""
    if not CURRENT_PLAN:
        return base_system
    return (
        f"{base_system}\n\n"
        f"[CURRENT PLAN]\n{format_plan(CURRENT_PLAN)}\n[end plan]"
    )


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
    return f"Plan updated ({len(CURRENT_PLAN)} steps):\n{format_plan(CURRENT_PLAN)}"


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
