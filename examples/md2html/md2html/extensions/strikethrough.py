"""Strikethrough extension.

Syntax:  ``~~text~~``  ->  ``<del>text</del>``

Inline-level. The text between a pair of double-tildes is rendered as a
``<del>`` element; its contents are parsed for further inline markup.
"""

from __future__ import annotations

from ..parser import ASTNode


class StrikethroughExtension:
    name = "strikethrough"

    def parse_inline(self, parser, text, i, out, buf) -> int:
        # Match an opening "~~".
        if not text.startswith("~~", i):
            return 0
        # Find the closing "~~".
        close = text.find("~~", i + 2)
        if close == -1:
            return 0
        inner = text[i + 2 : close]
        if not inner:
            return 0  # "~~~~" — nothing to strike

        # Flush any plain text accumulated before this node.
        if buf:
            out.append(ASTNode("text", value="".join(buf)))
            buf.clear()

        out.append(ASTNode("strikethrough", children=parser._parse_inline(inner)))
        return (close + 2) - i

    def render(self, renderer, node) -> str | None:
        if node.kind != "strikethrough":
            return None
        return f"<del>{renderer.render_children(node)}</del>"
