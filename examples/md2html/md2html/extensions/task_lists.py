"""Task list extension.

Syntax (GitHub-flavored):

    - [ ] an unchecked item
    - [x] a checked item

A list item whose text begins with ``[ ]`` or ``[x]`` (case-insensitive)
renders with a disabled checkbox prepended; ``[x]`` adds ``checked``. Ordinary
list items are passed through to the built-in handler unchanged.
"""

from __future__ import annotations

import re

from ..utils import html_escape

# Leading task marker: "[ ] " / "[x] " (case-insensitive), trailing space(s).
_RE_TASK = re.compile(r"^\[([ xX])\]\s+")


class TaskListsExtension:
    name = "task_lists"

    def render(self, renderer, node) -> str | None:
        if node.kind != "list_item":
            return None
        children = node.children
        if not children or children[0].kind != "text":
            return None
        m = _RE_TASK.match(children[0].value)
        if not m:
            return None  # ordinary list item — defer to the built-in

        checked = m.group(1).lower() == "x"
        checkbox = (
            '<input type="checkbox" disabled checked>'
            if checked
            else '<input type="checkbox" disabled>'
        )
        # Strip the marker from the first text node; render the rest of the
        # item's inline content (any nodes after the first) unchanged.
        rest = html_escape(children[0].value[m.end():])
        tail = "".join(renderer.render_node(c) for c in children[1:])
        return f"<li>{checkbox} {rest}{tail}</li>"
