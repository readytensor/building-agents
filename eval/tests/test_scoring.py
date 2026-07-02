from eval.scoring import score_pytest
from eval.tests.conftest import FAIL_TO_PASS, PASS_TO_PASS


def test_base_repo_scores_f2p_as_failing(base_repo):
    v = score_pytest(base_repo, FAIL_TO_PASS, PASS_TO_PASS)
    assert v.fail_to_pass == {"passed": [], "failed": ["test_math.py::test_add"]}
    assert v.pass_to_pass == {"passed": ["test_math.py::test_mul"], "failed": []}
    assert v.passed is False


def test_fixed_repo_scores_as_passing(base_repo):
    calc = base_repo / "calc.py"
    calc.write_text(calc.read_text().replace("return a - b", "return a + b"))
    v = score_pytest(base_repo, FAIL_TO_PASS, PASS_TO_PASS)
    assert v.fail_to_pass == {"passed": ["test_math.py::test_add"], "failed": []}
    assert v.passed is True


def test_missing_node_counts_as_failed(base_repo):
    v = score_pytest(base_repo, ["test_math.py::test_nope"], PASS_TO_PASS)
    assert v.fail_to_pass == {"passed": [], "failed": ["test_math.py::test_nope"]}
    assert v.passed is False
