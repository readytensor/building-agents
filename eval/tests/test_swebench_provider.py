import subprocess

import pytest

from eval.targets import swebench
from eval.tests.conftest import BASE_FILES


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


def test_record_to_instance_maps_fields(tmp_path):
    inst = swebench.to_instance(FAKE_RECORD, cache_dir=tmp_path)
    assert inst.id == "demo__demo-1"
    assert inst.problem_statement == "add() subtracts instead of adding."
    assert inst.fail_to_pass == ["test_math.py::test_add"]
    assert inst.pass_to_pass == ["test_math.py::test_mul"]
    assert callable(inst.prepare)
    # repo_dir points into the cache, keyed by repo + commit; not cloned yet.
    assert "demo" in str(inst.repo_dir) and "abc123" in str(inst.repo_dir)


def _local_remote(tmp_path):
    """A local git repo standing in for GitHub: commit1 = broken, commit2 = fixed."""
    remote = tmp_path / "remote"
    remote.mkdir()

    def git(*args):
        return subprocess.run(
            ["git", "-c", "user.email=e@e", "-c", "user.name=e", "-C", str(remote), *args],
            check=True, capture_output=True, text=True,
        ).stdout.strip()

    git("init", "-q")
    for name, content in BASE_FILES.items():
        (remote / name).write_text(content, encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "broken base")
    sha1 = git("rev-parse", "HEAD")
    calc = remote / "calc.py"
    calc.write_text(calc.read_text().replace("return a - b", "return a + b"), encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "fix")
    return remote, sha1


def test_clone_at_commit_checks_out_the_requested_state(tmp_path):
    remote, sha1 = _local_remote(tmp_path)
    dest = tmp_path / "cache" / "demo" / sha1
    swebench.clone_at_commit(str(remote), sha1, dest)
    # We asked for the BROKEN commit even though the remote's HEAD has the fix.
    assert "return a - b" in (dest / "calc.py").read_text()


def test_clone_at_commit_is_idempotent(tmp_path):
    remote, sha1 = _local_remote(tmp_path)
    dest = tmp_path / "cache" / "demo" / sha1
    swebench.clone_at_commit(str(remote), sha1, dest)
    swebench.clone_at_commit(str(remote), sha1, dest)  # second call: no error, cache hit
    assert "return a - b" in (dest / "calc.py").read_text()


def test_get_instances_without_datasets_gives_install_hint(monkeypatch):
    monkeypatch.setattr(swebench, "_load_dataset_records", None)
    with pytest.raises(RuntimeError) as exc:
        swebench.get_instances()
    assert "pip install datasets" in str(exc.value)
