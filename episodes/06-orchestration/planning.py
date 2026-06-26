"""
Episode 6 — Orchestration (planning, carried forward from Ep 4)

Ep 4's contribution — write_plan + think + the dynamic-system-prompt
mechanism — carried forward, but adapted to Ep 6's recursive runtime.

In Eps 4-5 the plan lived in a module-level global (one agent, one plan). Ep 6
runs many agents at once (the orchestrator plus parallel workers), so the plan
can't be global — each run_agent call owns its own plan list. make_plan_tool
binds a write_plan tool to a specific per-call plan via a closure; think is
stateless, so it stays a plain module-level tool. system_with_plan takes the
plan as an argument instead of reading a global.

Imports one-way from tools (`planning → tools`, for the @tool decorator).

See ../../README.md for context.
"""
import json

from tools import tool


def format_plan(plan: list[dict]) -> str:
    if not plan:
        return "(no plan set)"
    icons = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]"}
    lines = []
    for i, step in enumerate(plan, 1):
        icon = icons.get(step.get("status", "pending"), "[?]")
        lines.append(f"  {i}. {icon} {step.get('content', '')}")
    return "\n".join(lines)


def system_with_plan(base_system: str, plan: list[dict]) -> str:
    """The stable base prompt plus this agent's current plan appended. The loop
    calls this each turn and rebuilds messages[0] from the result, so the plan
    is always visible. With no plan set, this is just the base prompt."""
    if not plan:
        return base_system
    return f"{base_system}\n\n[CURRENT PLAN]\n{format_plan(plan)}\n[end plan]"


# write_plan's description + schema. The body is a no-op stub: the real
# implementation is the per-call closure make_plan_tool returns (it needs to
# mutate THIS agent's plan list). The decorator here exists only to publish the
# tool_definition the closure reuses.
@tool(
    "Set or update your working plan for a MULTI-STEP TASK. Pass the FULL "
    "current state of the plan as a list of steps. Each step can be either "
    "(a) a string describing the step, or (b) a dict with 'content' (string) "
    "and 'status' (one of 'pending', 'in_progress', 'completed'). Call this "
    "at the start of a multi-step task and again whenever you complete a step "
    "or revise your approach. The plan is always visible to you in subsequent "
    "iterations. USE THIS FOR: tracking progress through multiple distinct "
    "subtasks. NOT FOR: in-the-moment reasoning — for that, use `think`."
)
def write_plan(steps) -> str:
    raise RuntimeError("write_plan must be dispatched via make_plan_tool's per-call closure")


def make_plan_tool(plan: list[dict]):
    """Return a write_plan tool bound to `plan` (this agent's plan list). The
    closure mutates that specific list; it carries write_plan's schema so the
    model sees the same tool definition regardless of which agent owns it."""
    def _write_plan(steps) -> str:
        # Defensive: schema typing for list-of-X isn't tight, so the model
        # sometimes sends `steps` as a JSON-encoded string. Recover.
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
        return f"Plan updated ({len(plan)} steps):\n{format_plan(plan)}"
    _write_plan.tool_definition = write_plan.tool_definition
    return _write_plan


@tool(
    "Externalize your reasoning about a hard problem or decision. Pass a "
    "thought as a string; it is echoed back unchanged. The act of writing "
    "the thought out forces explicit reasoning before action. "
    "USE THIS FOR: weighing alternative approaches before choosing one, "
    "reasoning through a tricky edge case. NOT FOR: tracking multi-step "
    "task progress — for that, use `write_plan`."
)
def think(thought: str) -> str:
    return thought
