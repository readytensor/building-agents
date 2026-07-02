from eval.materialize import materialize, capture_diff


def test_materialize_copies_and_git_inits(base_repo, tmp_path):
    dest = tmp_path / "work"
    repo = materialize(base_repo, dest)
    assert (repo / "calc.py").exists()
    assert (repo / ".git").is_dir()


def test_capture_diff_reflects_an_edit(base_repo, tmp_path):
    repo = materialize(base_repo, tmp_path / "work")
    calc = repo / "calc.py"
    calc.write_text(calc.read_text().replace("return a - b", "return a + b"))
    diff = capture_diff(repo)
    assert "return a + b" in diff
    assert diff.startswith("diff --git")


def test_capture_diff_empty_when_unchanged(base_repo, tmp_path):
    repo = materialize(base_repo, tmp_path / "work")
    assert capture_diff(repo) == ""
