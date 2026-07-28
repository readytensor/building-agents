"""Held-out tests for the table-of-contents task (Episode 3).

These are the grader's tests, not the agent's: they live outside initial/
(so they are never copied into the sandbox) and grade.py injects them into
the sandbox AFTER a run finishes. They probe the parts of the contract the
visible fixture doesn't show — generalization, not the worked example.
"""

import re

from md2html import render


# --- Anchors ----------------------------------------------------------------

def test_anchor_on_every_heading_level():
    html = render("# Alpha One\n\n## Beta Two\n\n### Gamma Three\n")
    assert 'id="alpha-one"' in html
    assert 'id="beta-two"' in html
    assert 'id="gamma-three"' in html


def test_slug_is_lowercase_with_punctuation_stripped():
    html = render("# Hello, World! (v2.0)\n")
    slug = re.search(r'<h1 id="([^"]+)"', html).group(1)
    assert slug == slug.lower()
    assert re.fullmatch(r"[a-z0-9-]+", slug)


def test_duplicate_headings_get_distinct_sequential_ids():
    html = render("## Examples\n\na\n\n## Examples\n\nb\n\n## Examples\n\nc\n")
    ids = re.findall(r'<h2 id="([^"]+)"', html)
    assert ids == ["examples", "examples-1", "examples-2"]


# --- The [TOC] marker --------------------------------------------------------

def test_marker_replaced_with_labeled_nav():
    html = render("[TOC]\n\n# Intro\n\n## Setup\n\n## Usage\n\n### Advanced\n")
    assert '<nav class="toc">' in html
    assert '<p class="toc-title">Contents</p>' in html
    assert "[TOC]" not in html
    for slug in ("intro", "setup", "usage", "advanced"):
        assert f'href="#{slug}"' in html


def test_toc_nesting_follows_heading_levels():
    html = render("[TOC]\n\n# A\n\n## B\n\n### C\n")
    nav = html.split('<nav class="toc">')[1].split("</nav>")[0]
    assert nav.count("<ul") >= 2 or nav.count("<ol") >= 2


def test_label_is_not_a_list_entry():
    html = render("[TOC]\n\n# Only Section\n")
    nav = html.split('<nav class="toc">')[1].split("</nav>")[0]
    # The label must not be linked or listed - one heading means one link.
    assert nav.count("<a ") == 1
    assert "Contents</a>" not in nav


def test_toc_hrefs_match_heading_ids_exactly():
    html = render("[TOC]\n\n## My Section!\n")
    heading_id = re.search(r'<h2 id="([^"]+)"', html).group(1)
    assert f'href="#{heading_id}"' in html


# --- Opt-in behavior ----------------------------------------------------------

def test_no_marker_means_anchors_but_no_nav():
    html = render("# Solo\n\nbody text\n")
    assert 'id="solo"' in html
    assert '<nav class="toc">' not in html
    assert "toc-title" not in html
