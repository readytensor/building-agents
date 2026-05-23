# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project actually is

This is a **video-series planning workspace**, not a software project. The deliverable is a 5-episode technical video series titled **"Agents from First Principles"** produced by **Clyep** (the technical-video arm of Ready Tensor, Inc.). The series teaches engineers how agents actually work, using a progressively-built coding agent as the worked example.

## Read these first

1. **[`README.md`](./README.md)** — the working source of truth. Carries the original brief forward with all design decisions made since. Contains: series arc, episode-by-episode plan, code progression, scope boundaries, the companion code repo structure, the `initial/` → `sandbox/` reset pattern, code conventions.
2. **[`building-agents-series.v1.md`](./building-agents-series.v1.md)** — the original snapshot brief. Reference, not source of truth.
3. **`tmp/about-clyep/`** — Clyep brand, ICP, production strengths. Read to understand the audience and aesthetic the series must fit.
4. **`tmp/agent-sdk/` and `tmp/blog/`** — Browser Use's open-source `bu-agent-sdk` and the "Bitter Lesson of Agent Frameworks" blog post. **Inspiration only**, not the project deliverable. Code shapes, framings, diagrams here are fair to *adapt* — never copy verbatim.

## Working in this directory

When the user asks for help, they almost always mean **content planning, script/outline work, structural decisions, or pedagogical framing** — not feature work on the reference code in `tmp/`. The reference code is inspiration.

For exploratory design questions ("what do you think?", "how should we approach X?"), respond in 2–3 sentences with a recommendation and the main tradeoff, presented as redirectable. Don't move into implementation/planning artifacts until the user agrees on direction.

## Locked design decisions (decisions, not just preferences)

These have been settled across planning conversations. Build on them; don't re-derive. See `README.md` for the full rationale behind each.

- **One connected coding-agent toy across all 5 episodes.** Coding agent is the worked example.
- **The toy *task* forces each episode's failure mode** — not extra scaffolding code. Minimal code per episode; the task's natural difficulty does the work.
- **Episode arc (code additions):**
  - Ep 1 — `while`-loop + one tool (`bash`) + naive stop condition. ~60–80 lines.
  - Ep 2 — add a few general primitives (`read`, `write`, `grep`), a tiny `@tool`/schema helper, skills as named Python helpers.
  - Ep 3 — **rolling-summary compaction** + **done tool (`TaskComplete`)** — paired around the theme of *making long-running tasks reliable*.
  - Ep 4 — plan step (TODO scratchpad) + reflect step (on error or repeated calls). Pure focus on planning/reflection — done tool has already moved to Ep 3.
  - Ep 5 — multi-agent: second agent instance + `delegate(subtask)` tool.
- **LLM SDK: `openai` Python package against the Chat Completions API** (not the Responses API). Provider-portable via `base_url` override. No provider-specific features used.
- **Sandbox treatment: light touch.** ~60 seconds in Ep 1 when `bash` appears, showing the `SandboxContext` pattern. Full guardrails / durable execution / production ops are out of scope.
- **Companion code repo: folder-per-episode** (`episodes/01-loop/`, etc.) with each episode containing `agent.py`, `initial/` (pristine template, committed), and `sandbox/` (agent's working dir, gitignored, reset on every run). Reset is in the first 5 lines of `agent.py` — `shutil.copytree(initial, sandbox)` — so re-running is deterministic.
- **Toy codebase: `md2html`** — a small but properly-structured Markdown-to-HTML CLI with real module boundaries (lexer / parser / renderer / extensions / CLI) and a pytest suite. Full spec in [`spec/md2html.md`](./spec/md2html.md) — architecture, markdown subset, extensions, CLI, file-by-file responsibilities, Ep 1's `initial/` state, and forward-looking sketch of per-episode divergences.
- **Capstone (real-project) episode is deferred.** Decide after Ep 4. If kept, it's a looser documentary companion piece.
- **Framing principle for scope:** *Things that change the agent's shape are in scope. Things that wrap around it aren't.* Out of scope (separate series candidates): durable execution, full guardrails, production ops, prompt engineering at the token level, framework reviews, model training/RL.

## Open decisions

- **Per-episode `initial/` states for Ep 2–5.** Sketched in `spec/md2html.md` section 8 but not yet detailed. To be fleshed out as separate planning artifacts when each episode is being prepared. The episode-2 planted bug, episode-3 refactor target, episode-4 ambiguous failure, and episode-5 LaTeX-renderer spec all need pinning before implementation.
- **Implementation details of `md2html` itself.** Function signatures, `Token`/`Node` class layouts, extension registration mechanism, parser strategy (recursive-descent vs. table-driven vs. hand-rolled state machine) — deferred to the code-writing phase, not the spec.
- **The `md2html` implementation itself.** Skeleton scaffolding is in place under `code/episodes/01-loop/initial/` (a README placeholder), but the actual ~1,200 LOC of `md2html` source + tests has not been written. Needed before Ep 1's `agent.py` can be filled in (the agent needs something real to explore).
- **Ep 1 `agent.py` body.** The 5-line sandbox-reset bootstrap is in place; the rest of the agent loop (openai client setup, `bash` tool definition, the `while` loop, naive stop condition) is TODO. ~60-80 lines target.

## Code skeleton

The companion code repo's skeleton lives at `code/` in this workspace (will be split out to its own public repo when ready). See `code/README.md` and `code/episodes/<N>-*/README.md` for the per-episode entry points. Every `agent.py` already includes the 5-line `initial/` → `sandbox/` bootstrap; the agent loop itself is TODO in each.
