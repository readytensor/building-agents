"""
Episode 5 — Skills (planning, carried forward from Ep 4)

Ep 4's contribution, carried forward unchanged: the write_plan tool plus the
dynamic system-prompt mechanism that ties it in. Ep 5's skill system builds
directly on this mechanism — loaded-skill bodies ride into the system prompt
the same way the plan does (see skills.system_with_skills).

write_plan(steps) is a structured plan that lives in agent *state* (the
CURRENT_PLAN global), not in message history. Each iteration the loop rebuilds
the system prompt with the current plan appended (see system_with_plan), so the
plan is always in front of the model and — because it lives in state, not
messages — survives compaction untouched.

Imports one-way from tools (`planning → tools`, for the @tool decorator).
agent.py owns the base SYSTEM string and calls system_with_plan() each turn.

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
        f"[CURRENT PLAN]\n{format_plan(CURRENT_PLAN)}\n"
        "Keep this plan current — if it's stale, call write_plan before your "
        "next major action or before stopping.\n[end plan]"
    )


@tool(
    "Set or update your working plan for a MULTI-STEP TASK. Pass the FULL "
    "current state of the plan as a list of steps — each a string, or a dict "
    "with 'content' and 'status' ('pending' | 'in_progress' | 'completed'). "
    "Use it at the start of a task with several distinct subtasks to lay out "
    "the steps, and call it again as you go to keep the statuses current — "
    "marking a step 'in_progress' when you start it and 'completed' when it's "
    "done. The plan stays visible to you every turn and lives in agent state, "
    "so it survives compaction."
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
