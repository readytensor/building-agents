# Episode 2 — Tools — Spec

This document specifies what changes between Episode 1 and Episode 2: both the agent itself (`code/episodes/02-tools/agent.py`) and the toy codebase state in `code/episodes/02-tools/initial/`.

For Ep 2's narrative purpose see [`../tmp/video-creation-notes/episode-02.md`](../tmp/video-creation-notes/episode-02.md) — *to be written once we've implemented and verified the spec below*.

---

## 1. The exercise

### Task given to the agent

A realistic copy-paste of a pytest failure. The user pasted what they saw in their terminal and asked for help:

```python
TASK = """I'm seeing this when I run pytest in this repo:

FAILED tests/test_renderer.py::test_fixture_pair[escaped_backticks]
AssertionError: rendered HTML doesn't match expected.
See tests/fixtures/escaped_backticks.md / escaped_backticks.html
for the input and what the output should be.

Can you figure out what's wrong and fix it?"""
```

This task framing is the convention for **all later episodes** — the agent's prompt should read like something an engineer typed (paste-of-error + ask), not like a benchmark prompt.

### Success criterion

- All tests pass after the agent's work.
- The fix is in `parser.py` (not in test fixtures — i.e., the agent didn't "fix" the test by changing the expected output).
- The agent verified by running `pytest` after applying the fix.

The success criterion is **verifiable mechanically** (`pytest` exit code), which is the point of Ep 2 — the test suite is now the verification surface, and the agent uses it.

---

## 2. The planted bug

### Behavior

In `md2html/parser.py`, the inline parser's backslash-escape handler has a hard-coded set of characters it recognizes as escapable. This set includes `*`, `_`, `[`, `]`, `(`, `)`, `\\`, and similar — but **not** `` ` ``.

As a result, `\`literal\`` (intended: literal backticks) is parsed as `\` + start-of-code-span + `literal` + end-of-code-span + `\` — producing something like `<code>literal</code>` with stray backslashes around it, instead of `` `literal` `` in the output.

### Where it lives

`md2html/parser.py`, in the inline-parsing character scanner. Specifically: the backslash-escape handling, where there's a constant like `ESCAPABLE = {"*", "_", "[", "]", "(", ")", "\\", "!", ...}` that omits `` ` ``.

### The fix the agent should apply

Add `` ` `` to the escapable-character set. ~1 line of code change.

### Why this bug

- **In a central module** (parser.py), not buried in an extension — pedagogically dense.
- **Real-feeling.** This is a genuine error from the original implementation — escapable-character sets are easy to forget items in. Not a contrived bug.
- **Localizable from the failing test.** The fixture name (`escaped_backticks`) plus the failure diff points the agent directly at parser.py.
- **Small fix.** One-line change. Doesn't require restructuring.
- **Exercises the multi-tool design.** Agent will plausibly: run pytest → read fixture pair → grep for "backslash" or "escape" or `ESCAPABLE` → read parser.py → apply edit → re-run pytest.

### What does NOT change in `parser.py`

The `\*`, `\_`, `\[`, etc. paths still work correctly — every other escapable character continues to function. The bug is *specifically* missing-backtick. This keeps the failure scoped to exactly one test, not a cascade.

---

## 3. New test fixture

A new pair of files under `tests/fixtures/`:

### `tests/fixtures/escaped_backticks.md`

```markdown
Here are \`literal backticks\` in a sentence.

Also \`one with **bold** inside\` should preserve the literals.

A combination: regular `code` next to \`an escaped pair\` works correctly.
```

### `tests/fixtures/escaped_backticks.html`

```html
<p>Here are `literal backticks` in a sentence.</p>
<p>Also `one with **bold** inside` should preserve the literals.</p>
<p>A combination: regular <code>code</code> next to `an escaped pair` works correctly.</p>
```

This fixture tests three things:
1. The basic case (escaped pair in plain text).
2. The escape is robust enough to preserve other markdown inside (the `**bold**` between escaped backticks stays literal).
3. Escaped backticks coexist with real code spans in the same line.

With the bug present, **only the escaped-backticks test fails**. All other test pairs (`basic`, `headings`, `lists`, `tables`, `footnotes`, `nested`, `blockquotes`, `hr`, `inline`, `code_blocks`) still pass.

---

## 4. Tools added to the agent

From Episode 1's one tool (`bash`) to Episode 2's **five tools**.

### The argument for adding tools beyond `bash`

`bash` already covers everything — `cat` reads, `echo > file` writes, `sed` edits, `grep` searches. The agent in Ep 1 worked fine with just `bash`. So *why* add specific tools?

**Not capability — affordance.** Three reasons:

1. **Clear intent in traces.** A tool call named `edit(path, old, new)` reads more clearly than a `sed -i 's/.../.../' file` invocation. Producers, debuggers, and the agent itself benefit.
2. **Stronger model affordance via schema.** The model sees `edit(path: str, old_string: str, new_string: str)` and knows exactly what's possible. With `bash`, it has to remember and construct shell syntax.
3. **Validatable inputs.** Schema validation happens before the side-effecting code runs.

These are **architectural** reasons, not capability ones. The episode should land that explicitly.

### The five tools

| Tool | Signature | Behavior |
|---|---|---|
| `bash` | `bash(command: str) -> str` | Same as Ep 1. Kept as the escape hatch (running tests, anything not covered by the other tools). |
| `read` | `read(path: str) -> str` | Returns the file's contents with line-number prefixes (`  1\t...`). Path is relative to `sandbox/`. |
| `write` | `write(path: str, content: str) -> str` | Writes content to the file, overwriting if it exists. Creates parent directories as needed. Returns `"Wrote N bytes to <path>"`. |
| `edit` | `edit(path: str, old_string: str, new_string: str) -> str` | Replaces the *first occurrence* of `old_string` with `new_string` in the file. Returns success or "string not found." If `old_string` matches more than once, returns an error rather than guessing — the agent has to disambiguate. |
| `grep` | `grep(pattern: str, path: str = ".") -> str` | Searches files under `path` for the regex `pattern`. Returns lines as `relative/path:line: matched line`, up to a sensible cap (~50 results). |

All five tools have the same sandbox boundary as Ep 1: paths resolve relative to `sandbox/`, escape attempts (`../../etc/passwd`) raise.

### Why these specific four (not, say, `find` or `move`)?

The four cover the four operations a coding agent does most: **read, write, edit (surgical), search**. Anything else (`find`, `mv`, `rm`, etc.) the agent can do via `bash`. Keeping the named-tool count to 5 honors the "few general tools" lesson.

### Tool-dispatch robustness (added near the end of the episode)

Wrap the `result = fn(**args)` line in a `try/except` block that catches `TypeError`, `KeyError`, `json.JSONDecodeError`, and `ValueError`. On error, build an error-message string and feed it back to the model as the tool result instead of crashing the agent. ~5 added LOC.

**Why these exception types:**
- `TypeError` — model called a tool with missing/extra/wrong-named args (common: `bash()` with no `command`).
- `KeyError` — model called a tool name not in the registry (hallucinated tool).
- `JSONDecodeError` — malformed JSON in `tc.function.arguments`.
- `ValueError` — arg-validation failures inside tools (e.g., invalid regex passed to `grep`).

**Why this lives in Ep 2 and not Ep 1:** Ep 1 has one tool (`bash`) with one parameter (`command`); the model essentially can't get the schema wrong. Ep 2's expansion to 5 tools with varied signatures is the first time malformed tool calls become a real failure mode.

**Why "near the end" of the episode**: the lesson — *"the model will sometimes hallucinate tool args; route errors back to it as messages, don't crash"* — is real and architectural, but it's a 30-second mention, not a main beat. Treating it as a closing micro-addition ("one important thing before we close — here's 5 lines we added") keeps Ep 2's main narrative focused on tools + the `@tool` decorator. Ep 3 inherits the pattern unchanged.

---

## 5. The `@tool` decorator

Adding 4 tools by hand would mean ~80 lines of JSON-schema boilerplate at the bottom of `agent.py`. The decorator collapses that to one line per tool.

### What it does

Inspects a Python function's signature and type hints, builds the JSON-schema tool definition, attaches it to the function as `func.tool_definition`. Doesn't change how the function executes.

### Approximate shape

```python
def tool(description: str):
    """Attach a JSON-schema tool definition to a Python function."""
    def decorator(func):
        # Inspect signature, build properties from type hints,
        # mark required parameters (those without defaults).
        # Attach as func.tool_definition.
        ...
        return func
    return decorator
```

Implementation target: **~25 lines including the type-to-JSON-schema mapping** (`str` → `"string"`, `int` → `"integer"`, etc.). Smaller than that loses clarity; larger than that means we're adding features (per-parameter descriptions, Pydantic support, Annotated metadata) that belong in later episodes if at all.

### Explicit non-features

- No support for Pydantic model parameters (Ep 2 doesn't need it).
- No support for `Annotated[T, Depends(...)]` dependency injection (out of scope for this series — the reference SDK has this; we're staying minimal).
- No support for per-parameter descriptions in the docstring (could add later; not now).
- No support for default values in the JSON schema (the JSON `default` keyword) — required-vs-optional via the `required` array is enough.

The decorator should look "obviously achievable" to the viewer — 25 lines they could write themselves.

---

## 6. Skills — mentioned only

**No new tool gets added for "skills."** The episode mentions the concept with ~30 seconds of narration and an on-screen example, but the actual `agent.py` keeps the 5 tools above.

The on-screen example (illustrative, not in the code):

```python
# A "skill" is just a function. It can be a tool the agent calls,
# or a helper the engineer uses interactively. There's no abstraction.
@tool("Run the test suite and report results.")
def run_tests() -> str:
    return bash("pytest -q")
```

The lesson is **"skills are not a new concept."** They're functions composed from primitives. The moment you find yourself reaching for the same bash invocation repeatedly, you wrap it in a function and give it a name — and if useful for the model, you decorate it as a tool. That's it.

This framing matters because some agent frameworks (and some marketing) treat skills as a distinct architectural concept with its own machinery. Ours doesn't. The Ep 2 narration should be explicit about that.

---

## 7. CLI session — brief acknowledgment

The agent is still **one-shot** in Ep 2 — task in, final answer out, script exits. Multi-turn interactive sessions are not a teaching beat in this series.

But ~30 seconds in Ep 2 (probably near the closing) should acknowledge that the **interactive form is a 5-line wrapper** around what we have:

```python
# Brief on-screen sketch (NOT canonical code):
while True:
    task = input("> ")
    if not task: break
    run_agent(task)   # the function form of what we built
```

The framing: *"Claude Code, Gemini CLI, anything that feels like a REPL — same loop inside. We've stayed one-shot because the architectural lessons land cleaner that way. Making it interactive is a wrapper, not a redesign."*

This costs nothing pedagogically and prevents the question "but how do real coding agents do back-and-forth?" from lingering.

---

## 8. Expected agent trajectory

Not deterministic, but a plausible path:

1. `bash("pytest -q")` — reproduce the failure, see the assertion diff.
2. `read("tests/fixtures/escaped_backticks.md")` — see the input.
3. `read("tests/fixtures/escaped_backticks.html")` — see the expected output.
4. `grep("escape", "md2html")` or `grep("backslash", "md2html")` — find where escaping is handled.
5. `read("md2html/parser.py")` — locate the inline parser and the `ESCAPABLE` set (or whatever it's actually called in the impl).
6. `edit(...)` — add backtick to the escapable set.
7. `bash("pytest -q")` — verify all tests pass.
8. Final response: explains what was wrong and what was changed.

Step count target: **8–15 tool calls** (more than Ep 1's 16–22 if the agent explores broadly, less if it goes directly to parser.py).

Variance is expected and welcome — same teaching moment as Ep 1, slightly less prominent.

---

## 9. What changes in `agent.py`

### Diff sketch from Ep 1

**Removed:**
- The single `BASH_TOOL` dict (now built by the decorator).
- The narrow `tools=[BASH_TOOL]` passed to the LLM call.

**Added:**
- `@tool` decorator definition (~25 lines).
- 4 new tool functions: `read`, `write`, `edit`, `grep` (~10-15 lines each).
- Decoration of `bash` with `@tool("Execute a shell command...")` (1 line).
- Tool registry: `TOOLS_BY_NAME = {t.__name__: t for t in [bash, read, write, edit, grep]}`.
- Loop dispatch by name: `fn = TOOLS_BY_NAME[tc.function.name]; result = fn(**args)`.

**Unchanged:**
- Sandbox reset (5 lines, identical).
- LLM client setup (identical).
- System prompt (verbatim from Ep 1).
- Loop structure (`while True:` … naive stop on no tool calls).

The naive stop condition stays — done tool doesn't arrive until Ep 3.

### LOC growth

| | LOC (approx) |
|---|---|
| Ep 1 `agent.py` | ~90 |
| Ep 2 `agent.py` | ~150–170 |

The growth is justified by **eliminating boilerplate**. Without `@tool`, 5 tools = 5 schema dicts ≈ 80 extra lines. With `@tool`, 5 tools = 5 one-line decorator strings + the decorator itself ≈ 25 + 5 = 30 lines. The decorator pays for itself by the third tool.

---

## 10. What changes in `initial/`

`code/episodes/02-tools/initial/` is `md2html` exactly as in Ep 1's `initial/` **plus the planted bug and the new fixture pair**:

1. **`md2html/parser.py`** — the escapable-character set is missing `` ` ``. (One-character omission from a literal set.)
2. **`tests/fixtures/escaped_backticks.md`** — new, as specified in §3.
3. **`tests/fixtures/escaped_backticks.html`** — new, as specified in §3.

Nothing else changes. Every other test should pass when run against the buggy `initial/` — only the new fixture-pair test fails.

---

## 11. Out of scope for this episode

Reaffirming, in case the implementation drifts:

- **Done tool / `TaskComplete`.** Stays out until Ep 3.
- **Compaction.** Stays out until Ep 3.
- **Planning / reflection.** Stays out until Ep 4.
- **Multi-agent / delegation.** Stays out until Ep 5.
- **Pydantic-model tool parameters, Annotated/Depends.** Stays out of the series entirely (architectural focus, not framework features).
- **CLI-session REPL wrapping.** Acknowledged in ~30 sec, not implemented as canonical code.
- **`run_tests` as a real tool.** The skills concept gets a mention, not a sixth tool.

---

## 12. Implementation order (when we get there)

When implementing Ep 2 we'll do these in sequence:

1. Copy `code/episodes/01-loop/initial/` → `code/episodes/02-tools/initial/`.
2. Plant the bug in parser.py.
3. Add the `escaped_backticks` fixture pair.
4. Verify pytest now fails on exactly that one test.
5. Write `code/episodes/02-tools/agent.py` per §9.
6. Run the agent against the bugged `initial/` 3-4 times, capture trajectories, compare to Ep 1's variance behavior.
7. Iterate on tool descriptions / system prompt only if the trajectories show the agent struggling unnecessarily.
8. Write the producer brief (`tmp/video-creation-notes/episode-02.md`) using the same shape as Ep 1's.
