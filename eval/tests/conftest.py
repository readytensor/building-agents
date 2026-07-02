import subprocess
from pathlib import Path

import pytest

# A minimal "buggy" project: add() is wrong, so test_add fails (FAIL_TO_PASS);
# test_mul passes and must stay passing (PASS_TO_PASS).
BASE_FILES = {
    "calc.py": "def add(a, b):\n    return a - b\n\n\ndef mul(a, b):\n    return a * b\n",
    "test_math.py": (
        "from calc import add, mul\n\n\n"
        "def test_add():\n    assert add(2, 3) == 5\n\n\n"
        "def test_mul():\n    assert mul(2, 3) == 6\n"
    ),
}

FAIL_TO_PASS = ["test_math.py::test_add"]
PASS_TO_PASS = ["test_math.py::test_mul"]


def _git(repo: Path, *args):
    subprocess.run(
        ["git", "-c", "user.email=eval@example.com", "-c", "user.name=eval", *args],
        cwd=repo, check=True, capture_output=True, text=True,
    )


@pytest.fixture
def base_repo(tmp_path):
    """A committed git working copy in its base (failing) state."""
    repo = tmp_path / "base"
    repo.mkdir()
    for name, content in BASE_FILES.items():
        (repo / name).write_text(content, encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    return repo


def fixing_solver(repo_dir: Path, problem_statement: str) -> str:
    """A fake agent that correctly fixes add() in place, then returns its diff."""
    target = repo_dir / "calc.py"
    target.write_text(
        target.read_text(encoding="utf-8").replace("return a - b", "return a + b"),
        encoding="utf-8",
    )
    _git(repo_dir, "add", "-A")
    return subprocess.run(
        ["git", "-C", str(repo_dir), "diff", "--cached"],
        check=True, capture_output=True, text=True,
    ).stdout


def noop_solver(repo_dir: Path, problem_statement: str) -> str:
    """A fake agent that changes nothing (test_add stays failing)."""
    return ""


@pytest.fixture
def solvers():
    return {"fixing": fixing_solver, "noop": noop_solver}
