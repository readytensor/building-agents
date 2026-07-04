import pytest

from eval.targets import swebench


# A fake SWE-bench Verified record. Field shapes mirror the real dataset:
# FAIL_TO_PASS / PASS_TO_PASS are JSON-encoded string lists.
FAKE_RECORD = {
    "instance_id": "demo__demo-1",
    "repo": "demo/demo",
    "base_commit": "abc123",
    "problem_statement": "add() subtracts instead of adding.",
    "test_patch": "",
    "FAIL_TO_PASS": '["test_math.py::test_add"]',
    "PASS_TO_PASS": '["test_math.py::test_mul"]',
    "difficulty": "<15 min fix",
}


def test_record_to_instance_maps_fields():
    inst = swebench.to_instance(FAKE_RECORD)
    assert inst.id == "demo__demo-1"
    assert inst.problem_statement == "add() subtracts instead of adding."
    assert inst.fail_to_pass == ["test_math.py::test_add"]
    assert inst.pass_to_pass == ["test_math.py::test_mul"]
    assert inst.meta == {"difficulty": "<15 min fix", "repo": "demo/demo"}


def test_instance_is_container_backed_with_no_host_state():
    inst = swebench.to_instance(FAKE_RECORD)
    # No host checkout at all: the workspace is the image's own /testbed.
    assert inst.repo_dir is None
    assert inst.prepare is None
    assert callable(inst.env_setup)
    assert callable(inst.capture)  # diff leaves the container as text


def test_capture_diffs_the_active_container_against_base_commit(monkeypatch):
    monkeypatch.setattr(swebench.container, "ACTIVE", "cid9")
    calls = []
    monkeypatch.setattr(
        swebench.container, "capture_diff",
        lambda cid, base_commit=None: calls.append((cid, base_commit)) or "THE DIFF")
    inst = swebench.to_instance(FAKE_RECORD)
    assert inst.capture() == "THE DIFF"
    # The record's base_commit pins the diff target: an in-container
    # `git commit` must not be able to empty the captured patch.
    assert calls == [("cid9", "abc123")]


def test_get_instances_without_datasets_gives_install_hint(monkeypatch):
    monkeypatch.setattr(swebench, "_load_dataset_records", None)
    with pytest.raises(RuntimeError) as exc:
        swebench.get_instances()
    assert "pip install datasets" in str(exc.value)
