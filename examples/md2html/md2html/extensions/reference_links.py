"""Reference-style link extension.

Syntax:

    Here is a [link text][myref] in a paragraph.

    [myref]: https://example.com "Optional title"

Definition lines (``[id]: url "title"``) are collected during lexing,
stripped from the rendered output, and used to resolve ``[text][id]``
inline references into ``<a>`` elements.

Keys are case-insensitive and the title is optional.  Definitions may
appear anywhere in the document (before or after the references that
use them).

Implementation notes
--------------------
Because inline parsing happens *inside* block parsing (one paragraph at
a time), and link definitions may appear *after* the paragraphs that
reference them, we cannot resolve ids during inline parsing.  Instead:

1. The lexer hook intercepts definition lines and emits TK_REF_LINK_DEF
   tokens so they never reach the paragraph accumulator.
2. The parser's ``parse_block`` hook turns those tokens into
   ``ref_link_def`` AST nodes.
3. The inline hook emits ``ref_link`` nodes carrying only the ``ref_id``
   string — resolution is deferred.
4. ``post_parse`` strips ``ref_link_def`` nodes from the tree and stores
   the complete ``{id -> {href, title}}`` map in ``root.attrs``.
5. The renderer ``render`` hook intercepts the document node first so it
   can cache the definition map on ``renderer.state``; subsequent
   ``ref_link`` nodes then look up the map there.
"""

from __future__ import annotations

import re

from ..lexer import Token
from ..parser import ASTNode

# -----------------------------------------------------------------------
# Token kind
# -----------------------------------------------------------------------

TK_REF_LINK_DEF = "ref_link_def"

# -----------------------------------------------------------------------
# Patterns
# -----------------------------------------------------------------------

# Block-level definition line:  [id]: url  or  [id]: url "title"
# The id may contain any characters except ']' and must not start with '^'
# (that prefix is reserved for footnote definitions).
# The url may be bare or angle-bracket-wrapped.
# The optional title may be in "", '', or ().
_RE_DEF = re.compile(
    r'^[ \t]{0,3}'
    r'\[(?P<id>[^\]^][^\]]*)\]:'       # id: not starting with '^'
    r'[ \t]+'
    r'(?P<url>(?:<[^>]*>|[^\s]*))'
    r'(?:'
        r'[ \t]+'
        r'(?P<title>"[^"]*"|\'[^\']*\'|\([^)]*\))'
    r')?'
    r'[ \t]*$'
)

# Matches the second bracket pair in [text][ref-id], anchored at its '['.
_RE_REFBRACKET = re.compile(r'\[(?P<id>[^\]]*)\]')


class ReferenceLinksExtension:
    name = "reference_links"

    # -------------------------------------------------------------------
    # Lexer hook — consume definition lines before they become paragraphs
    # -------------------------------------------------------------------

    def tokenize_block(self, lexer) -> bool:
        line = lexer.line()
        m = _RE_DEF.match(line)
        if not m:
            return False
        ref_id = m.group("id").strip().lower()
        url = m.group("url") or ""
        if url.startswith("<") and url.endswith(">"):
            url = url[1:-1]
        title = m.group("title") or ""
        if title and title[0] in "\"'(":
            title = title[1:-1]
        lexer.advance()
        lexer.emit(Token(TK_REF_LINK_DEF, url, {"id": ref_id, "title": title}))
        return True

    # -------------------------------------------------------------------
    # Parser: block hook — turn token into an AST definition node
    # -------------------------------------------------------------------

    def parse_block(self, parser, tok):
        if tok.kind != TK_REF_LINK_DEF:
            return None
        parser.advance()
        return ASTNode(
            "ref_link_def",
            attrs={
                "id": tok.attrs["id"],
                "href": tok.value,
                "title": tok.attrs["title"],
            },
        )

    # Parser: post-parse hook — build the lookup table and prune def nodes

    def post_parse(self, root, parser):
        """Collect every ref_link_def from the top-level child list into a
        ``{lowercased-id -> {href, title}}`` map stored on ``root.attrs``,
        then remove those nodes so they produce no rendered output.
        """
        defs: dict[str, dict] = {}
        new_children: list[ASTNode] = []
        for child in root.children:
            if child.kind == "ref_link_def":
                # First definition for an id wins (CommonMark rule).
                defs.setdefault(
                    child.attrs["id"],
                    {"href": child.attrs["href"], "title": child.attrs["title"]},
                )
            else:
                new_children.append(child)
        root.children = new_children
        root.attrs["ref_link_defs"] = defs

    # -------------------------------------------------------------------
    # Parser: inline hook — match [text][ref-id] and emit a ref_link node
    # -------------------------------------------------------------------

    def parse_inline(self, parser, text, i, out, buf):
        """Match ``[link text][ref-id]`` starting at *i* (must be '[').

        Returns the number of characters consumed, or 0 for no match.
        The node carries only the ``ref_id``; the URL is resolved later
        by the renderer once the full definition map is available.
        """
        if text[i] != "[":
            return 0

        n = len(text)

        # Walk the label brackets, respecting escapes and nesting.
        depth = 1
        j = i + 1
        while j < n and depth > 0:
            c = text[j]
            if c == "\\" and j + 1 < n:
                j += 2
                continue
            if c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
                if depth == 0:
                    break
            j += 1

        if depth != 0 or j >= n:
            return 0  # unclosed bracket

        label = text[i + 1 : j]         # text between the first [...]
        after_close = j + 1             # index right after the closing ']'

        # Must be immediately followed by '[id]'
        if after_close >= n or text[after_close] != "[":
            return 0

        m = _RE_REFBRACKET.match(text, after_close)
        if not m:
            return 0

        ref_id = m.group("id").strip().lower()
        if not ref_id:
            return 0

        # Flush any accumulated plain text before our node.
        if buf:
            out.append(ASTNode("text", value="".join(buf)))
            buf.clear()

        link_node = ASTNode(
            "ref_link",
            children=parser._parse_inline(label),
            attrs={"ref_id": ref_id},
        )
        out.append(link_node)
        return m.end() - i  # total chars consumed (both bracket pairs)

    # -------------------------------------------------------------------
    # Renderer hooks
    # -------------------------------------------------------------------

    def init_state(self, renderer):
        # Seed the slot; it's populated when the document node is visited.
        renderer.state["ref_link_defs"] = {}

    def render(self, renderer, node):
        """Intercept two node kinds:

        * ``document`` — seed the definition map from ``root.attrs`` so
          every subsequent ``ref_link`` node can resolve it.
        * ``ref_link`` — emit the resolved ``<a>`` tag.
        * ``ref_link_def`` — silently suppress (belt-and-suspenders guard
          in case one slipped past ``post_parse``).
        """
        if node.kind == "document":
            # Cache the map early so ref_link nodes below can use it.
            renderer.state["ref_link_defs"] = node.attrs.get("ref_link_defs", {})
            # Return None to let the built-in visit_document handle layout.
            return None

        if node.kind == "ref_link_def":
            return ""  # no output for stray definition nodes

        if node.kind == "ref_link":
            defs = renderer.state.get("ref_link_defs", {})
            ref_id = node.attrs.get("ref_id", "")
            entry = defs.get(ref_id, {})
            href = entry.get("href", "")
            title = entry.get("title", "")

            from ..utils import html_escape
            href_attr = html_escape(href)
            title_attr = f' title="{html_escape(title)}"' if title else ""
            inner = renderer.render_children(node)
            return f'<a href="{href_attr}"{title_attr}>{inner}</a>'

        return None  # not our node — fall through to built-in dispatch
