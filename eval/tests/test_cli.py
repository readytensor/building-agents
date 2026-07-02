import json

import pytest

from eval import run_eval
from eval.tests.conftest import BASE_FILES


def _md2html_stub(tmp_path):
    base = tmp_path / "md2html"
    base.mkdir()
    for name, content in BASE_FILES.items():
        (base / name).write_text(content, encoding="utf-8")
    return base


def test_cli_fake_agent_end_to_end(tmp_path, monkeypatch):
    base = _md2html_stub(tmp_path)
    specs = [{
        "id": "md2html__demo",
        "problem_statement": "Fix add.",
        "fail_to_pass": ["test_math.py::test_add"],
        "pass_to_pass": ["test_math.py::test_mul"],
    }]
    # Point the local provider at the stub tree + specs.
    from eval.targets.local import build_instances
    monkeypatch.setattr(run_eval, "load_local_instances", lambda: build_instances(base, specs))

    results_root = tmp_path / "results"
    code = run_eval.main([
        "--source", "local", "--agent", "fake-fixing", "--n", "1",
        "--seed", "0", "--results-root", str(results_root), "--timestamp", "t0",
    ])
    assert code == 0

    board = (results_root / "scoreboard.jsonl").read_text().strip().splitlines()
    assert len(board) == 1
    row = json.loads(board[0])
    assert row["pass_at_1"] == 1.0
    assert (results_root / "t0" / "summary.md").exists()
    verdict = json.loads((results_root / "t0" / "md2html__demo" / "verify.json").read_text())
    assert verdict["passed"] is True


def test_grade_flag_requires_swebench_source():
    with pytest.raises(SystemExit, match="--grade needs --source swebench"):
        run_eval.main(["--source", "local", "--agent", "fake-noop", "--grade"])
