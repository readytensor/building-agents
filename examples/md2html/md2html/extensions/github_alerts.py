"""GitHub-flavored alert extension.

Syntax (all five types GitHub supports):

    > [!NOTE]
    > Useful information that users should know.

    > [!TIP]
    > Helpful advice for doing things better or more easily.

    > [!IMPORTANT]
    > Key information users need to know to achieve their goal.

    > [!WARNING]
    > Urgent info that needs immediate user attention to avoid problems.

    > [!CAUTION]
    > Advises about risks or negative outcomes of certain actions.

A blockquote whose first line is exactly ``[!TYPE]`` (case-insensitive) is
rendered as a ``<div>`` with the classes ``markdown-alert`` and
``markdown-alert-<type>`` (lowercase), matching GitHub's output.

Source: https://docs.github.com/en/get-started/writing-on-github/getting-started-with-writing-and-formatting-on-github/basic-writing-and-formatting-syntax#alerts
Class names confirmed via antfu/markdown-it-github-alerts (explicitly states
it is compatible with GitHub's HTML output).

Regular blockquotes (those whose first line is not ``[!TYPE]``) are passed
through to the built-in blockquote handler unchanged.
"""

from __future__ import annotations

import re

from ..lexer import TK_BLOCKQUOTE_LINE
from ..parser import ASTNode

# Matches the alert-type line exactly: [!NOTE], [!TIP], etc.
_RE_ALERT_MARKER = re.compile(
    r"^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\][ \t]*$",
    re.IGNORECASE,
)


class GitHubAlertsExtension:
    name = "github_alerts"

    # ------------------------------------------------------------------
    # Parser hook: intercept blockquote tokens that are alerts.
    # ------------------------------------------------------------------

    def parse_block(self, parser, tok) -> ASTNode | None:
        if tok.kind != TK_BLOCKQUOTE_LINE:
            return None

        lines = tok.value.split("\n")
        m = _RE_ALERT_MARKER.match(lines[0])
        if not m:
            # Not an alert — let the built-in blockquote handler take it.
            return None

        # Consume the token from the stream.
        parser.advance()

        alert_type = m.group(1).upper()   # canonical: "NOTE", "TIP", …
        # Title-case: "NOTE" -> "Note", "IMPORTANT" -> "Important", etc.
        title = alert_type.capitalize()

        # The body is everything after the marker line.
        body_text = "\n".join(lines[1:]).strip()

        # Re-lex and re-parse the body so that it handles paragraphs,
        # inline markup, code spans, etc., exactly as any other block.
        from ..lexer import Lexer
        from ..parser import Parser as _Parser

        inner_tokens = Lexer(body_text, extensions=parser.extensions).tokenize()
        inner_ast = _Parser(inner_tokens, extensions=parser.extensions).parse()

        return ASTNode(
            "github_alert",
            children=inner_ast.children,
            attrs={"alert_type": alert_type.lower(), "title": title},
        )

    # ------------------------------------------------------------------
    # Renderer hook: emit the alert HTML.
    # ------------------------------------------------------------------

    def render(self, renderer, node) -> str | None:
        if node.kind != "github_alert":
            return None

        alert_type = node.attrs["alert_type"]   # e.g. "note"
        title = node.attrs["title"]             # e.g. "Note"

        # Render each child block (paragraphs, code blocks, …) and join
        # them with newlines, mirroring visit_document's approach.
        body_parts = [renderer.render_node(c) for c in node.children]
        body = "\n".join(p for p in body_parts if p)

        title_html = f'<p class="markdown-alert-title">{title}</p>'

        # Inner content: newline after opening tag, title, body, newline
        # before closing tag — matching GitHub's actual HTML structure.
        inner = f"\n{title_html}\n{body}\n"
        return (
            f'<div class="markdown-alert markdown-alert-{alert_type}">'
            f"{inner}"
            f"</div>"
        )
