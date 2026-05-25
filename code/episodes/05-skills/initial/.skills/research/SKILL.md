---
name: research
description: Use when you need information you don't have in your training — library docs, spec details, recent feature behavior, exact API shapes — and want to gather authoritative answers before acting.
tools: [web_search, fetch_url]
---

# Research

When the task references a URL, an API spec, a library feature you're
unsure about, or anything that changes faster than your training data:
search and read first, code second.

## When to use this

- The task explicitly says "check the latest docs" or gives a URL.
- You're about to implement against a library/spec where exact details
  matter (class names, attribute strings, version-specific behavior).
- You'd otherwise be writing from memory on something that may have
  changed since your training cutoff.

## When NOT to use this

- The task is about first-principles work (algorithms, language
  semantics) where your training is authoritative.
- You've already searched once and have what you need.
- Local files in the project already contain the answer.

## How to use

1. `web_search("<short query>")` for an initial scan — read the first
   2–3 result titles + snippets.
2. `fetch_url("<authoritative URL>")` for the source of truth (official
   docs > vendor blog > third-party tutorial > random GitHub gist).
3. Triangulate when stakes are high: at least one official source plus
   one independent confirmation.
4. Note what you actually used. A `think()` call or a code comment
   pointing to the URL lets a reviewer (or future-you) verify.

## Counter-patterns

- Confidently implementing from memory when the task explicitly said
  "check the docs." If you weren't certain enough to skip searching,
  you're not certain enough to skip verifying.
- Searching once, taking the first hit, treating it as ground truth.
- Trusting AI-generated summaries (Stack Overflow answers, AI-written
  blog posts) over primary sources (vendor docs, RFCs, source code).
- Pretending you searched when you didn't.
