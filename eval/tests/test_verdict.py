from eval.targets import Verdict


def test_passed_true_when_all_f2p_pass_and_no_p2p_fail():
    v = Verdict(
        fail_to_pass={"passed": ["a", "b"], "failed": []},
        pass_to_pass={"passed": ["c"], "failed": []},
    )
    assert v.passed is True


def test_passed_false_when_any_f2p_fails():
    v = Verdict(
        fail_to_pass={"passed": ["a"], "failed": ["b"]},
        pass_to_pass={"passed": ["c"], "failed": []},
    )
    assert v.passed is False


def test_passed_false_when_a_p2p_regresses():
    v = Verdict(
        fail_to_pass={"passed": ["a"], "failed": []},
        pass_to_pass={"passed": [], "failed": ["c"]},
    )
    assert v.passed is False


def test_passed_false_when_no_f2p_ran():
    v = Verdict(
        fail_to_pass={"passed": [], "failed": []},
        pass_to_pass={"passed": ["c"], "failed": []},
    )
    assert v.passed is False
