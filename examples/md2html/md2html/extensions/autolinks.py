"""Autolink extension.

Syntax:  ``<https://example.com>``  ->
         ``<a href="https://example.com">https://example.com</a>``

Inline-level. An angle-bracket-wrapped absolute URL (``scheme://...``) becomes
a link whose ``href`` and visible text are both the URL.
"""

from __future__ import annotations

import re

from ..parser import ASTNode
from ..utils import html_escape

# <scheme://rest> — a normal URI scheme followed by "://" and a run of
# non-space, non-angle-bracket characters.
_RE_AUTOLINK = re.compile(r"<([a-zA-Z][a-zA-Z0-9+.\-]*://[^<>\s]+)>")


class AutolinksExtension:
    name = "autolinks"

    def parse_inline(self, parser, text, i, out, buf) -> int:
        if text[i] != "<":
            return 0
        m = _RE_AUTOLINK.match(text, i)
        if not m:
            return 0
        url = m.group(1)

        if buf:
            out.append(ASTNode("text", value="".join(buf)))
            buf.clear()

        out.append(ASTNode("autolink", attrs={"url": url}))
        return m.end() - i

    def render(self, renderer, node) -> str | None:
        if node.kind != "autolink":
            return None
        url = html_escape(node.attrs.get("url", ""))
        return f'<a href="{url}">{url}</a>'
