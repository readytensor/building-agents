"""list_files and grep skip noise dirs (VCS internals, caches, build output),
so their output caps (200 files, 50 matches) are spent on real source -- big
real-world repos vendor whole build trees that would otherwise eat the budget."""


def _noisy_sandbox(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("needle = 1\n", encoding="utf-8")
    for noise in (".git", "build", "__pycache__"):
        (tmp_path / noise).mkdir()
        (tmp_path / noise / "b.py").write_text("needle = 2\n", encoding="utf-8")
    return tmp_path


def test_grep_skips_noise_dirs(monkeypatch, tmp_path):
    import eval.agent  # noqa: F401  (puts Ep 5's modules on sys.path)
    import tools
    monkeypatch.setattr(tools, "SANDBOX", _noisy_sandbox(tmp_path))
    out = tools.grep(pattern="needle", path=".")
    assert "a.py" in out
    assert "build" not in out and ".git" not in out


def test_list_files_skips_noise_dirs(monkeypatch, tmp_path):
    import eval.agent  # noqa: F401
    import tools
    monkeypatch.setattr(tools, "SANDBOX", _noisy_sandbox(tmp_path))
    out = tools.list_files(path=".")
    assert "a.py" in out
    assert "build" not in out and ".git" not in out
