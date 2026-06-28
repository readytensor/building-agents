"""
Episode 6 — Subagents (compaction)

Ep 3's headline mechanism, carried forward unchanged: rolling-summary
compaction. When the compactable *middle* of the message history grows past
COMPACTION_THRESHOLD, that middle is summarized via a second LLM call and
replaced with one summary message — so a long-running task doesn't keep paying
for the full transcript every turn.

In Ep 6 each worker runs its own loop with its own message history, so compact()
is called per-worker, on per-call state. The function is unchanged and stateless
(it takes the messages, client, and model as arguments), so the same code serves
the orchestrator and every worker. We trigger on the token count of
the *middle* — the part that actually gets summarized — not the whole call's
input. Counting the total would fire on tokens compaction can't touch (the system
prompt + the preserved recent rounds), so it could trigger with nothing to
shrink. The middle is counted with tiktoken (a real token count; for non-OpenAI
providers it's an approximation, but exact enough for a go/no-go trigger).

compact() needs an LLM to write the summary, so it takes the `client` and
`model` as arguments rather than importing them — that keeps the import one-way
(`agent → compaction`, like `agent → tools`) and avoids a circular import with
agent.py. Because they're passed in, the caller is free to summarize on a cheaper
model (even a different provider) than the main loop — agent.py resolves which
from the LLM_SUMMARIZER_* env vars.

See ../../README.md for context.
"""
import os

from tiktoken import get_encoding

# tiktoken encoder for measuring the middle's size (the part we summarize).
# cl100k_base is OpenAI's tokenizer; for Claude/others it's an approximation, but
# a real token count is plenty for a go/no-go "is the middle big enough" trigger.
_ENC = get_encoding("cl100k_base")

# --- Compaction knobs. Env-overridable; defaults shown below. Both are used in
# compact(): the threshold gates on the middle's token count, KEEP sets the tail.
COMPACTION_THRESHOLD = int(os.environ.get("COMPACTION_THRESHOLD", 20_000))  # tokens in the compactable middle before we summarize it.
KEEP_LAST_ITERATIONS = int(os.environ.get("KEEP_LAST_ITERATIONS", 2))            # recent assistant rounds preserved uncompacted.

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
            # Safeguard only: cap a single pathologically large tool output so one
            # giant dump can't blow up the summarizer call. 5K chars leaves normal
            # tool results intact, so the summarizer sees ~what the agent saw — the
            # content that actually drove the compaction trigger.
            preview = content if len(content) < 5000 else content[:5000] + "...[truncated]"
            out.append(f"TOOL RESULT: {preview}")
        else:
            out.append(f"{role.upper()}: {content}")
    return "\n\n".join(out)


def _count_tokens(messages):
    """Actual token count (tiktoken) of the full content of these messages — the
    middle we'd be summarizing. Counts message content + tool-call arguments."""
    parts = []
    for m in messages:
        parts.append(str(m.get("content") or ""))
        for tc in (m.get("tool_calls") or []):
            parts.append(str(tc.get("function", {}).get("arguments", "")))
    return len(_ENC.encode("\n".join(parts)))


def compact(messages, client, model):
    """Summarize the middle of `messages`, preserving system prompt, original
    task, and the last K rounds. Returns (new_messages, did_compact, in, out,
    middle_tokens) — middle_tokens is the compactable middle's size (the trigger
    metric), returned every turn so the per-iter sawtooth can be plotted."""
    asst_positions = [i for i, m in enumerate(messages) if m.get("role") == "assistant"]
    if len(asst_positions) <= KEEP_LAST_ITERATIONS:
        return messages, False, 0, 0, 0
    head = messages[:2]                            # system + original user task
    tail_start = asst_positions[-KEEP_LAST_ITERATIONS]
    middle = messages[2:tail_start]
    tail = messages[tail_start:]
    if not middle:
        return messages, False, 0, 0, 0

    # Fire only when the MIDDLE (what we'd summarize) is big enough to be worth a
    # summarizer call. Counting the middle — not the total input — means we never
    # fire on tokens compaction can't shrink (head + the preserved recent rounds).
    # middle_tokens is returned every turn (fired or not) for the per-iter sawtooth.
    middle_tokens = _count_tokens(middle)
    if middle_tokens <= COMPACTION_THRESHOLD:
        return messages, False, 0, 0, middle_tokens

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
    return head + [summary_msg] + tail, True, su.prompt_tokens, su.completion_tokens, middle_tokens
