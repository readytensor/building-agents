from eval import container


def test_image_name_applies_docker_hub_transform():
    # Docker Hub repo names can't contain "__"; SWE-bench publishes them with
    # the "_1776_" replacement.
    assert container.image_for("pallets__flask-5014") == \
        "swebench/sweb.eval.x86_64.pallets_1776_flask-5014:latest"


def test_start_runs_detached_without_host_mounts(tmp_path):
    calls = []

    def fake_run(cmd):
        calls.append(cmd)
        return "abc123\n"

    cid = container.start("pallets__flask-5014", runner=fake_run)
    assert cid == "abc123"
    cmd = calls[0]
    assert cmd[:3] == ["docker", "run", "-d"]
    assert "--rm" in cmd
    # The agent works on the image's own /testbed: nothing from the host.
    assert "-v" not in cmd
    assert "swebench/sweb.eval.x86_64.pallets_1776_flask-5014:latest" in cmd
    assert "sleep" in cmd  # keep-alive command present
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
    # The command runs under the container's own `timeout`, so a runaway
    # process dies inside the container, not just the docker exec client.
    assert f"timeout -k 5 {container.BASH_TIMEOUT} bash -c" in script


def test_exec_reports_in_container_timeout(monkeypatch):
    captured = {}

    def fake_exec_run(cmd, timeout):
        captured["host_timeout"] = timeout
        return ("partial output", 124)  # coreutils timeout's exit code

    monkeypatch.setattr(container, "_exec_run", fake_exec_run)
    out = container.exec_bash("abc123", "python runaway.py")
    assert "timed out after 120s inside the container and was killed" in out
    # The host-side timeout is only a fallback for docker wedging: it fires
    # after the in-container one, never before.
    assert captured["host_timeout"] > container.BASH_TIMEOUT


def test_fileop_pipes_the_ops_module_plus_one_dispatch_call():
    captured = {}

    def fake_runner(cmd, program):
        captured["cmd"], captured["program"] = cmd, program
        return "    1\tx = 1"

    out = container.fileop("abc123", "read", {"path": "pkg/mod.py", "offset": 1},
                           runner=fake_runner)
    assert out == "    1\tx = 1"
    # stdin-fed python: content travels on stdin, no shell in the middle.
    assert captured["cmd"] == ["docker", "exec", "-i", "abc123",
                               "/opt/miniconda3/bin/python", "-"]
    assert "def dispatch" in captured["program"]        # the ops module itself
    assert '\\"op\\": \\"read\\"' in captured["program"]  # the payload, embedded
    assert captured["program"].rstrip().endswith('end="")')


def test_capture_diff_stages_then_diffs_before_teardown():
    calls = []

    def fake_run(cmd):
        calls.append(cmd)
        return "THE DIFF" if "diff" in cmd else ""

    diff = container.capture_diff("abc123", runner=fake_run)
    assert diff == "THE DIFF"
    assert calls[0][:4] == ["docker", "exec", "abc123", "git"]
    assert "add" in calls[0] and "-A" in calls[0]        # new files enter the diff
    assert "--cached" in calls[1]
    assert any("exclude" in part for part in calls[1])   # build junk stays out


def test_stop_clears_active():
    calls = []
    container.ACTIVE = "abc123"
    container.stop("abc123", runner=lambda cmd: calls.append(cmd) or "")
    assert container.ACTIVE is None
    assert calls[0][:3] == ["docker", "rm", "-f"]


def test_remove_image_removes_the_instance_image():
    calls = []

    def fake_run(cmd):
        calls.append(cmd)
        return ""

    assert container.remove_image("pallets__flask-5014", runner=fake_run) is True
    assert calls == [["docker", "rmi",
                      "swebench/sweb.eval.x86_64.pallets_1776_flask-5014:latest"]]


def test_remove_image_tolerates_failure():
    # Image already gone / still in use: cleanup only costs disk, it must
    # never raise into a finished sample.
    def fake_run(cmd):
        raise RuntimeError("No such image")

    assert container.remove_image("pallets__flask-5014", runner=fake_run) is False
