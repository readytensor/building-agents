from pathlib import Path

from eval import container


def test_image_name_applies_docker_hub_transform():
    # Docker Hub repo names can't contain "__"; SWE-bench publishes them with
    # the "_1776_" replacement.
    assert container.image_for("pallets__flask-5014") == \
        "swebench/sweb.eval.x86_64.pallets_1776_flask-5014:latest"


def test_start_runs_detached_with_bind_mount(tmp_path):
    calls = []

    def fake_run(cmd):
        calls.append(cmd)
        return "abc123\n"

    cid = container.start("pallets__flask-5014", tmp_path, runner=fake_run)
    assert cid == "abc123"
    cmd = calls[0]
    assert cmd[:3] == ["docker", "run", "-d"]
    assert "--rm" in cmd
    mount = cmd[cmd.index("-v") + 1]
    assert mount.endswith(":/testbed")
    assert str(tmp_path.name) in mount
    assert cmd[-1] == "swebench/sweb.eval.x86_64.pallets_1776_flask-5014:latest" or \
        "sleep" in cmd  # image + keep-alive command present
    assert container.ACTIVE == "abc123"
    container.ACTIVE = None


def test_exec_activates_conda_env_and_runs_in_testbed():
    captured = {}

    def fake_run(cmd):
        captured["cmd"] = cmd
        return "ok"

    out = container.exec_bash("abc123", "pytest -q", runner=fake_run)
    assert out == "ok"
    cmd = captured["cmd"]
    assert cmd[:3] == ["docker", "exec", "abc123"]
    script = cmd[-1]
    assert "activate testbed" in script
    assert "cd /testbed" in script
    assert "pytest -q" in script


def test_stop_clears_active():
    calls = []
    container.ACTIVE = "abc123"
    container.stop("abc123", runner=lambda cmd: calls.append(cmd) or "")
    assert container.ACTIVE is None
    assert calls[0][:3] == ["docker", "rm", "-f"]
