# Agents from First Principles
### A 5-part technical video series

---

## What this series is

AI agents — Claude Code, Cursor, browser-use, research agents — share a surprisingly small architectural core. A model, a tool set, a loop, a stop condition, a way to manage what the model can see. Everything else is refinement.

Most public discourse about agents is either marketing or engineering philosophy. The middle layer — *here's what an agent actually is at the code level, here's why the design choices look the way they do* — is underserved.

This series fills that gap. We build a working agent from scratch, episode by episode, using each addition as a lens to examine the real architectural questions: what an agent is, why tools converge on small general primitives, why context matters more than prompts, what fails and why, when structure earns its complexity, and when one agent becomes many.

The worked example is a coding agent. It's the cleanest domain to learn in — tight feedback loop, small tool surface, strong model performance. But each episode surfaces where the same principles apply in other domains: research agents, browser automation, data pipelines.

---

## Who this is for

Engineers and technical practitioners who use agents, are building them, or want to read new agent releases critically. The series assumes Python fluency and comfort calling LLM APIs. It does not assume prior agent-building experience.

---

## Purpose

Give viewers a durable mental model of how agents actually work, grounded in a simple progressive implementation. Not expert-level mastery. Not toy-level hand-waving. Real architecture, simple code, honest about what's hard.

By the end, viewers should be able to build a basic agent, extend it deliberately, debug it when it breaks, and evaluate any agent system they encounter — including production ones — with real conceptual footing.

---

## Learning outcomes

By the end of the series, viewers will be able to:

- Explain what an agent is at the architectural level, not the marketing level
- Build a minimal working agent and understand every part of it
- Design a small, composable tool surface that generalizes across tasks
- Diagnose why an agent is performing poorly and know which lever to pull
- Add planning and reflection only when it earns its complexity
- Reason about when multi-agent systems help versus when they just add abstraction

---

## Series arc

Each episode answers the next natural question a curious person asks after the previous one. A viewer who stops after any episode has a complete answer to a real question — not a fragment waiting to pay off later.

| # | Episode | Core question | Standalone value |
|---|---|---|---|
| 1 | **The Loop** | What is an agent? | A working agent they can run and modify today |
| 2 | **Tools** | How does it actually do things? | An agent with real capabilities; intuition for tool design |
| 3 | **Context** | Why does it get worse on longer tasks? | The most important practical insight in the series |
| 4 | **Planning, Reflection, and Failure** | Why does it spiral — and how do you fix it? | A more robust agent; architecture intuitions that transfer everywhere |
| 5 | **Orchestration** | When is one agent the wrong shape? | A clear framework for when multi-agent adds value vs. overhead |

---

## Episodes

### Episode 1 — The Loop
**Core question:** What is an agent?

Strip away the frameworks, the streaming UI, the integrations. What's left is a model in a loop with tools and a stop condition. This episode builds that minimal version — roughly 80 lines of Python — and runs it on a real task end-to-end.

The goal isn't to impress with capability. It's to make the abstraction concrete. Every agent the viewer will ever encounter is a refinement of this pattern. Claude Code, browser-use, research agents — same loop, more machinery.

**What the viewer leaves with:** A working agent they understand completely, and a mental model that lets them read any agent system critically.

---

### Episode 2 — Tools
**Core question:** How does the agent actually do things?

The episode-1 agent can reason, but it can't act. Tools are what change that. This episode adds a small set of general primitives — file operations, code execution, search — and shows the agent using them to solve a task it couldn't before.

The key architectural move: demonstrating why a few general tools beat many narrow ones. A Python REPL subsumes dozens of specialized tools through composition. This episode also introduces **skills** as a lightweight idea — not a new abstraction, just reusable patterns built from the same general tools. Named helpers that the agent (or the engineer) reaches for repeatedly.

**What the viewer leaves with:** An agent with real capabilities, and intuition for why production systems converge on small tool surfaces.

---

### Episode 3 — Context
**Core question:** Why does the same agent succeed on some tasks and fail on others?

Take the episode-2 agent and give it a task that breaks it — something long enough that it starts losing the thread, repeating steps, or forgetting what it was doing. Show exactly why: the context window is filling, and the agent is losing access to the information it needs.

Then fix it. A rolling summary, selective history, or explicit task state tracker — one simple mechanism that makes the agent materially more reliable. The lesson is the most important one in the series: **agent capability is mostly context quality, not prompt cleverness**. Performance is downstream of what the model can see, not just what you told it at the start.

**What the viewer leaves with:** A clear diagnosis for the most common class of agent failure, and a practical tool for fixing it.

---

### Episode 4 — Planning, Reflection, and Failure
**Core question:** Why does it spiral — and how do you fix it?

This episode starts with a failure gallery: runaway loops, hallucinated progress, premature stopping, scope drift. Each failure is shown concretely, then traced to a specific architectural gap. The failures aren't random — they're predictable, and each one points directly at a fix.

The fixes are planning and reflection, introduced as solutions to real problems rather than abstract patterns. A lightweight plan step before the loop. A reflect step when a tool fails or the agent gets stuck. The episode ends honestly: these additions cost latency and introduce their own failure modes. The engineering is knowing when to gate them.

**What the viewer leaves with:** A more robust agent, and the architectural intuition to read any agent system — including production ones — and understand what each safety mechanism is reacting to.

---

### Episode 5 — Orchestration and Sub-agents
**Core question:** When is one agent the wrong shape for a problem?

Take a task that genuinely strains the single-agent architecture — context overload, conflicting responsibilities, or parts of the task that benefit from different modes of operation. Show where it breaks, then split it: a planner that decomposes and coordinates, an executor that carries out. Keep the code simple. The concept is the point.

The honest framing: multi-agent systems are useful when tasks decompose cleanly, when parallelism matters, or when context boundaries are real constraints. When those conditions don't hold, orchestration is just routing overhead. The episode closes with the genuine open questions in the field — coordination failures, trust between agents, context handoffs — rather than pretending they're solved. That's an honest place to leave a viewer who now has real conceptual footing.

**What the viewer leaves with:** A clear framework for when multi-agent adds value, and a view into where the field's hard problems actually are.

---

## What this series doesn't cover

**Prompt engineering at the token level.** Context engineering is the craft; prompt tuning is downstream of that.

**Specific framework reviews.** LangChain, LlamaIndex, CrewAI — these are implementations of the patterns covered, not the patterns themselves.

**Model training and RL.** Out of scope by design. The series takes the model as given.

**Production ops.** Deployment, monitoring, cost management — real concerns, different series.

Each exclusion is deliberate. The series promises depth on one thing: the architectural core of how agents work.

---

## Episode structure pattern

Every episode follows the same internal rhythm:

1. **One question** — what this episode answers
2. **One limitation** — what the current agent can't do
3. **One addition** — the new concept, in code
4. **One before/after** — concrete demonstration that the addition mattered
5. **One abstraction** — "this is the same pattern real systems use, just with more machinery"

The fifth beat is what makes the series feel like it opens something rather than closing it.

---

## Companion artifacts

- Public GitHub repo with tagged commits per episode — non-negotiable
- Each episode's code should be runnable independently, not just as part of a sequence