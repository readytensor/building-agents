# `md2html` — Toy Codebase Spec

The toy codebase used across all 5 episodes of "Agents from First Principles." A small but properly-structured Markdown-to-HTML CLI tool. The agent uses this as its working surface; episode tasks involve exploring, fixing, refactoring, debugging, and extending it.

**Design goals:**

- Real module boundaries (lexer / parser / renderer / extensions) so every episode's task lands on actual seams — not arbitrary splits.
- Compact enough to read in one sitting (~1,200 LOC including tests).
- Real pytest suite so the agent can verify its own work via `bash pytest`.
- Naturally extensible (Ep 5 adds LaTeX output as a second renderer).

---

## 1. Architecture

Three-stage pipeline:

```
markdown text → lexer → tokens → parser → AST → renderer → HTML
```

- **Lexer** (`lexer.py`) — scans raw markdown, produces a linear stream of block-level `Token` objects. Inline content within blocks is held as raw text and parsed later.
- **Parser** (`parser.py`) — consumes the token stream and produces an AST of `Node` objects. Handles block nesting (lists in blockquotes, lists in lists) and inline parsing (emphasis, links, code spans).
- **Renderer** (`renderer.py`) — walks the AST via the visitor pattern (`visit_<node_type>` methods) and emits HTML strings.

**Extensions** hook into all three stages — each extension contributes a tokenizer rule, AST node type, and renderer method, packaged in one file.

---

## 2. Markdown subset

### Block-level (core)

| Construct | Markdown | HTML |
|---|---|---|
| ATX heading 1–6 | `# H1` … `###### H6` | `<h1>H1</h1>` |
| Paragraph | `lorem ipsum` | `<p>lorem ipsum</p>` |
| Unordered list | `- item` / `* item` | `<ul><li>item</li></ul>` |
| Ordered list | `1. item` | `<ol><li>item</li></ol>` |
| Nested lists | (2- or 4-space indent) | nested `<ul>`/`<ol>` |
| Fenced code block | ` ``` … ``` ` | `<pre><code>…</code></pre>` |
| Blockquote | `> text` | `<blockquote>…</blockquote>` |
| Horizontal rule | `---` / `***` | `<hr/>` |

### Inline (core)

| Construct | Markdown | HTML |
|---|---|---|
| Emphasis | `*italic*` / `_italic_` | `<em>italic</em>` |
| Strong | `**bold**` / `__bold__` | `<strong>bold</strong>` |
| Inline code | `` `code` `` | `<code>code</code>` |
| Link | `[text](url)` | `<a href="url">text</a>` |
| Image | `![alt](url)` | `<img src="url" alt="alt"/>` |
| Hard break | trailing `  \n` | `<br/>` |

### Deliberately out of scope

To keep the spec tractable:

- HTML pass-through (raw `<div>` in markdown)
- Setext headings (underlined H1/H2)
- Indented code blocks (only fenced)
- Reference-style links
- Strikethrough, task lists, autolinks
- Math/LaTeX in markdown
- Tight vs. loose list semantics (always tight)

---

## 3. Extensions

Three extensions ship with v1, each self-contained in one file under `md2html/extensions/`.

### `tables.py` — GitHub-flavored tables

```markdown
| col1 | col2 |
|------|------|
|  a   |  b   |
```

Renders to `<table><thead>…</thead><tbody>…</tbody></table>`.

- Header row required (the `|---|---|` separator).
- Cell alignment via `|:---|---:|:---:|` (left/right/center) — supported.

### `code_blocks.py` — fenced code with language tag

Augments the core fenced-code tokenizer to capture the language tag:

````markdown
```python
def foo(): pass
```
````

Renders to `<pre><code class="language-python">def foo(): pass</code></pre>`.

No actual syntax highlighting — just the class attribute. Keeps the dependency surface zero.

### `footnotes.py` — footnote refs and definitions

```markdown
Here is a footnote[^1].

[^1]: This is the footnote text.
```

Inline ref renders as `<sup><a href="#fn-1">1</a></sup>`. Definitions collected into a `<section class="footnotes">` at the document end.

- Refs and defs can appear in any order.
- Numeric or named keys both supported (`[^note]` works).

---

## 4. CLI

```
md2html INPUT_FILE [-o OUTPUT_FILE] [--stdout]
        [--no-extensions] [--extensions LIST]
```

| Flag | Behavior |
|---|---|
| `INPUT_FILE` | Path to a `.md` file (required, positional). |
| `-o`, `--output` | Output `.html` path. Default: replace `.md` with `.html`. |
| `--stdout` | Write to stdout instead of a file. |
| `--no-extensions` | Disable all extensions; core markdown only. |
| `--extensions LIST` | Enable only the named extensions (comma-separated). |
| `-h`, `--help` | Standard argparse help. |

Examples:

```
md2html README.md                       # writes README.html
md2html README.md --stdout              # prints to stdout
md2html post.md --extensions tables     # tables only
md2html post.md --no-extensions         # core only
```

---

## 5. File-by-file responsibility

| File | Responsibility | Approx LOC |
|---|---|---:|
| `md2html/__init__.py` | Exports `Document`, `render`, `__version__` | ~20 |
| `md2html/cli.py` | argparse entry, reads input, calls `render`, writes output | ~60 |
| `md2html/lexer.py` | Markdown text → list of `Token`. Block-level scanning. | ~200 |
| `md2html/parser.py` | Token list → AST of `Node`. Block nesting + inline parsing. | ~180 |
| `md2html/renderer.py` | AST → HTML via visitor methods | ~120 |
| `md2html/utils.py` | HTML-escape, whitespace normalize, slugify | ~30 |
| `md2html/extensions/__init__.py` | Extension registry | ~30 |
| `md2html/extensions/tables.py` | Table token + `TableNode` + `visit_table` | ~100 |
| `md2html/extensions/code_blocks.py` | Augments fenced-code tokenizer with lang tag | ~50 |
| `md2html/extensions/footnotes.py` | Footnote token + node + renderer | ~110 |
| `tests/conftest.py` | pytest fixtures | ~20 |
| `tests/test_lexer.py` | Tokenizer unit tests | ~80 |
| `tests/test_parser.py` | AST construction tests | ~80 |
| `tests/test_renderer.py` | End-to-end fixture-based markdown→HTML tests | ~60 |
| `tests/fixtures/*.md` + `tests/fixtures/*.html` | Input + expected output pairs | ~10 file pairs |
| `pyproject.toml`, top-level `README.md` | Project metadata | — |

**Total: ~1,200 LOC of source + tests.**

---

## 6. Tests

The test suite is the agent's verification surface. After any code change, `bash pytest` should run cleanly.

- **Lexer tests** — unit tests on the tokenizer. Each block type plus edge cases (empty lines, mixed indentation, trailing whitespace, escaped characters).
- **Parser tests** — AST construction. Nesting cases (list-in-blockquote, list-in-list, blockquote-in-blockquote).
- **Renderer / end-to-end tests** — fixture-based. For each `tests/fixtures/foo.md`, compare `render(foo.md)` to `tests/fixtures/foo.html`. Easy to add new cases by dropping in a new file pair.

Fixtures cover the happy path for every core construct and every extension. At least one fixture per extension exercises edge cases (cell-alignment in tables, named-key footnotes, language-tag normalization in code blocks).

---

## 7. Episode 1 initial state

`episodes/01-loop/initial/` = **a complete, working `md2html` exactly as specified above.** Every feature implemented, every test passing.

The agent's Ep 1 task is to **explore this codebase and explain what it does** — no modifications expected. The fact that it's a real working tool rather than a half-built scaffolding is the point: viewers see the agent exploring real code, the way Claude Code does day-to-day.

For Ep 1 specifically, the agent should be able to produce a summary that names:

- The tool's purpose (markdown → HTML CLI)
- The three-stage pipeline (lexer / parser / renderer)
- That it has extensions and what they do
- That it has a test suite

A viewer evaluating the agent's output should be able to verify each of those claims against the codebase quickly.

---

## 8. Per-episode initial state (forward-looking)

Later episodes' `initial/` directories diverge from Ep 1's, but only in the minimum the lesson requires. **Each will be spec'd separately when that episode is being prepared.** Sketch:

| Ep | What changes from Ep 1's `initial/` | Agent's task |
|---|---|---|
| 2 | One planted bug in lexer, parser, or one extension; corresponding test fails | Find and fix the bug; tests pass |
| 3 | Same as Ep 1, possibly with one awkward naming or hook signature that's a refactor target | Multi-file refactor (e.g., `Token` → `Node`, or change a hook signature) |
| 4 | A failing test whose root cause is genuinely ambiguous across modules (e.g., "tables in nested lists render wrong") | Debug; ambiguity earns planning + reflection |
| 5 | Same as Ep 1 + a spec for a LaTeX renderer to be added | Add LaTeX as a second output format alongside HTML |

---

## 9. What this spec does *not* pin down

Implementation details left to the code-writing phase:

- Exact function signatures
- `Token` / `Node` class layouts (likely `@dataclass`-based, but not committed)
- Extension registration mechanism (plugin list? import-time discovery? entry-points?)
- Specific pytest setup beyond "uses pytest"
- Whether the parser is recursive-descent, table-driven, or hand-rolled state machine

These are deliberately deferred. The spec answers *what the tool is*. The code answers *how it's implemented*.
