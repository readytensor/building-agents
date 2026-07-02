---
name: research
description: Look things up on the web when you need information that may have changed since your training (APIs, formats, library behavior). Provides web_search and fetch_url.
tools: [web_search, fetch_url]
---

When the task depends on external facts that may have changed since your training:

1. web_search for the authoritative source first.
2. fetch_url the most authoritative result to read it in full.
3. Ground your implementation in what the source actually says, not memory.
