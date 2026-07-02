import pytest

from eval.targets.local import build_instances


def test_build_instances_produces_wellformed_instances(tmp_path):
    # A stand-in md2html base: enough that Instance fields are exercised.
    base = tmp_path / "md2html_base"
    base.mkdir()
    (base / "calc.py").write_text("def add(a, b):\n    return a - b\n")
    (base / "test_math.py").write_text(
        "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"
    )

    specs = [{
        "id": "md2html__demo",
        "problem_statement": "Fix add.",
        "fail_to_pass": ["test_math.py::test_add"],
        "pass_to_pass": [],
    }]
    instances = build_instances(base_dir=base, specs=specs)

    assert len(instances) == 1
    inst = instances[0]
    assert inst.id == "md2html__demo"
    assert inst.repo_dir == base
    assert inst.fail_to_pass == ["test_math.py::test_add"]
    assert callable(inst.scorer)


def test_ids_must_be_unique():
    specs = [
        {"id": "dup", "problem_statement": "", "fail_to_pass": [], "pass_to_pass": []},
        {"id": "dup", "problem_statement": "", "fail_to_pass": [], "pass_to_pass": []},
    ]
    with pytest.raises(ValueError):
        build_instances(base_dir=".", specs=specs)
