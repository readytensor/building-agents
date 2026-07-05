"""Token-free stand-in agents: the `solve(repo_dir, task) -> diff` contract
with no LLM behind it.

Both the test suite and the CLI's `--agent fake-*` smoke path use these, so
they live here rather than inside the tests (the CLI should not import test
internals, and conftest.py drags pytest into the import chain).
"""
import subprocess
from pathlib import Path


def git(repo: Path, *args):
    """Run a git command in `repo` with identity preset (fresh temp repos
    have no user.name/email configured)."""
    subprocess.run(
        ["git", "-c", "user.email=eval@example.com", "-c", "user.name=eval", *args],
        cwd=repo, check=True, capture_output=True, text=True,
    )


def fixing_solver(repo_dir: Path, problem_statement: str, audit=None) -> str:
    """A fake agent that correctly fixes add() in place, then returns its diff."""
    target = repo_dir / "calc.py"
    target.write_text(
        target.read_text(encoding="utf-8").replace("return a - b", "return a + b"),
        encoding="utf-8",
    )
    git(repo_dir, "add", "-A")
    return subprocess.run(
        ["git", "-C", str(repo_dir), "diff", "--cached"],
        check=True, capture_output=True, text=True,
    ).stdout


def noop_solver(repo_dir: Path, problem_statement: str, audit=None) -> str:
    """A fake agent that changes nothing (test_add stays failing)."""
    return ""
