"""Tests for the repo_map orientation tool: the mapper in container_fileops
(one implementation, used in-container and host-side) and its wiring in
eval/agent.py (the injected root map + the drill-down tool proxy).
All offline: synthetic trees, no docker, no LLM.
"""
from pathlib import Path

from eval import container_fileops as cf


def _make_repo(tmp_path: Path) -> Path:
    """A tiny but structurally realistic project: README + runner config,
    a package with a docstring and a subpackage, a tests/ dir with a
    conftest, and junk dirs that must be skipped."""
    (tmp_path / "README.md").write_text("# Proj\n", encoding="utf-8")
    (tmp_path / "tox.ini").write_text("[tox]\n", encoding="utf-8")
    (tmp_path / "setup.py").write_text("", encoding="utf-8")
    pkg = tmp_path / "pkg"
    (pkg / "sub").mkdir(parents=True)
    (pkg / "__init__.py").write_text(
        '"""Top package docstring.\n\nSecond paragraph."""\n', encoding="utf-8")
    (pkg / "mod.py").write_text(
        '"""Mod doc."""\n\n'
        "class Foo(Base):\n"
        "    def bar(self, x):\n"
        "        pass\n\n"
        "def top(a, b=1, *args, **kwargs):\n"
        "    pass\n", encoding="utf-8")
    (pkg / "sub" / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "sub" / "util.py").write_text("def helper():\n    pass\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "conftest.py").write_text("", encoding="utf-8")
    (tests / "test_mod.py").write_text("def test_x():\n    pass\n", encoding="utf-8")
    junk = tmp_path / "build"
    junk.mkdir()
    (junk / "junk.py").write_text("x = 1\n", encoding="utf-8")
    return tmp_path


def test_overview_names_readme_and_runner_config(tmp_path):
    out = cf.repo_map(_make_repo(tmp_path))
    assert "README: README.md" in out
    assert "tox.ini" in out
    assert "setup.py" in out


def test_overview_package_tree_with_docstring_one_liner(tmp_path):
    out = cf.repo_map(_make_repo(tmp_path))
    assert "pkg/ (2 modules) -- Top package docstring." in out
    assert "pkg/sub/ (2 modules)" in out


def test_overview_lists_test_locations(tmp_path):
    out = cf.repo_map(_make_repo(tmp_path))
    assert "tests/" in out.split("Test locations")[1]


def test_overview_skips_junk_dirs(tmp_path):
    out = cf.repo_map(_make_repo(tmp_path))
    assert "build/" not in out


def test_subtree_shows_signatures(tmp_path):
    out = cf.repo_map(_make_repo(tmp_path), "pkg")
    assert "pkg/mod.py -- Mod doc." in out
    assert "class Foo(Base)" in out
    assert "def bar(self, x)" in out
    assert "def top(a, b, *args, **kwargs)" in out
    assert "pkg/sub/util.py" in out  # recursive


def test_subtree_tolerates_syntax_errors(tmp_path):
    repo = _make_repo(tmp_path)
    (repo / "pkg" / "broken.py").write_text("def (\n", encoding="utf-8")
    out = cf.repo_map(repo, "pkg")
    assert "pkg/broken.py (could not parse)" in out
    assert "class Foo(Base)" in out  # the rest still mapped


def test_repo_map_on_a_file_is_an_error(tmp_path):
    repo = _make_repo(tmp_path)
    out = cf.repo_map(repo, "pkg/mod.py")
    assert out.startswith("Error:")


def test_repo_map_dispatches_as_an_op(tmp_path):
    out = cf.dispatch({"op": "repo_map", "path": "."}, root=_make_repo(tmp_path))
    assert "README: README.md" in out


def test_overview_truncates_huge_package_trees(tmp_path):
    repo = tmp_path
    for i in range(cf._DIR_CAP + 10):
        d = repo / f"pkg{i:03d}"
        d.mkdir()
        (d / "__init__.py").write_text("", encoding="utf-8")
    out = cf.repo_map(repo)
    assert "more directories" in out


def test_top_level_files_are_capped(tmp_path):
    for i in range(cf._TOPFILE_CAP + 20):
        (tmp_path / f"file{i:02d}.txt").write_text("", encoding="utf-8")
    out = cf.repo_map(tmp_path)
    assert "(+20 more)" in out


def test_output_is_hard_capped(tmp_path):
    # 300 long-named packages with long docstrings: line caps alone would
    # still emit ~20K chars; the hard cap must kick in.
    for i in range(300):
        d = tmp_path / f"averylongpackagedirectoryname{i:04d}"
        d.mkdir()
        (d / "__init__.py").write_text('"""' + "x" * 90 + '"""\n', encoding="utf-8")
    out = cf.repo_map(tmp_path)
    assert len(out) <= cf._MAP_CHAR_CAP + 100
    assert "map truncated" in out
