"""
Episode 4 — Planning & Thinking (compaction)

Ep 3's headline mechanism, carried forward unchanged: rolling-summary
compaction. When a single LLM call's input grows past COMPACTION_THRESHOLD, the
older middle of the message history is summarized via a second LLM call and
replaced with one summary message — so a long-running task doesn't keep paying
for the full transcript on every turn.

This file is identical to Ep 3's compaction.py. compact() takes the `client`
and `model` as arguments rather than importing them — that keeps the import
one-way (`agent → compaction`, like `agent → tools`) and avoids a circular
import with agent.py. Because they're passed in, the caller is free to
summarize on a cheaper model (even a different provider) than the main loop —
agent.py resolves which from the LLM_SUMMARIZER_* env vars.

See ../../README.md for context.
"""
import os

# --- Compaction knobs. Env-overridable; defaults shown below. The threshold is
# read by the agent loop (to decide when to fire); KEEP is used here.
COMPACTION_THRESHOLD = int(os.environ.get("EP3_THRESHOLD", 30_000))  # input tokens per single LLM call.
KEEP_LAST_ITERATIONS = int(os.environ.get("EP3_KEEP", 4))            # recent assistant rounds preserved uncompacted.

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


def compact(messages, client, model):
    """Summarize the middle of `messages`, preserving system prompt, original
    task, and the last K rounds. Returns (new_messages, did_compact, in, out)."""
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
    summary_resp = client.chat.completions.create(model=model, messages=summarizer_msgs)
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
