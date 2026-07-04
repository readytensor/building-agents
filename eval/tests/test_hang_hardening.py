"""Hang hardening, from the 2026-07-03 wedged batch: three workers sat silent
for 40 minutes inside LLM calls (the SDK's default is a 600s timeout with
silent retries), and a dead Docker engine fed error strings to the model
instead of failing the worker. A stalled worker must die loudly and quickly:
the dispatcher already reports worker failures and the batch resumes.
"""
import pytest

from eval import container


def test_llm_client_timeout_is_bounded(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    from eval.agent import _client
    client = _client("")
    assert client.timeout == 120.0
    assert client.max_retries == 2


def test_exec_bash_raises_when_the_container_is_gone(monkeypatch):
    monkeypatch.setattr(container, "_exec_run", lambda cmd, timeout:
                        ("Error response from daemon: No such container: abc123", 1))
    with pytest.raises(RuntimeError, match="No such container"):
        container.exec_bash("abc123", "pytest -q")


def test_exec_bash_returns_ordinary_failures_to_the_model(monkeypatch):
    # A failing test run is a normal outcome the model must see, not a crash.
    monkeypatch.setattr(container, "_exec_run", lambda cmd, timeout:
                        ("1 failed, 3 passed", 1))
    out = container.exec_bash("abc123", "pytest -q")
    assert "1 failed" in out and "exit code 1" in out


def test_fileop_raises_when_the_engine_is_unreachable(monkeypatch):
    class Proc:
        returncode = 1
        stdout = ""
        stderr = "error during connect: The system cannot find the file specified"

    monkeypatch.setattr(container.subprocess, "run", lambda *a, **k: Proc())
    with pytest.raises(RuntimeError, match="error during connect"):
        container.fileop("abc123", "read", {"path": "f.py"})


def test_fileop_returns_ordinary_errors_to_the_model(monkeypatch):
    class Proc:
        returncode = 1
        stdout = ""
        stderr = "SyntaxError: invalid payload"

    monkeypatch.setattr(container.subprocess, "run", lambda *a, **k: Proc())
    out = container.fileop("abc123", "read", {"path": "f.py"})
    assert out.startswith("Error:") and "SyntaxError" in out


def test_stop_tolerates_an_already_gone_container():
    # Teardown runs in a finally: raising there would mask the real failure.
    def dead_runner(cmd):
        raise RuntimeError("No such container: abc123")

    container.ACTIVE = "abc123"
    container.stop("abc123", runner=dead_runner)  # must not raise
    assert container.ACTIVE is None
