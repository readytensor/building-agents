from eval import container
from eval.targets import swebench
from eval.tests.test_swebench_provider import FAKE_RECORD


def test_bash_routes_into_container_when_active(monkeypatch):
    import eval.agent as agent
    calls = {}
    monkeypatch.setattr(container, "ACTIVE", "cid42")
    def fake_exec(cid, cmd):
        calls["args"] = (cid, cmd)
        return "container says hi"

    monkeypatch.setattr(container, "exec_bash", fake_exec)
    assert agent.bash(command="pytest -q") == "container says hi"
    assert calls["args"] == ("cid42", "pytest -q")


def test_bash_falls_back_to_host_when_no_container(monkeypatch, tmp_path):
    import eval.agent as agent
    import tools  # Ep 5's module, on sys.path via eval.agent
    monkeypatch.setattr(container, "ACTIVE", None)
    monkeypatch.setattr(tools, "SANDBOX", tmp_path)
    out = agent.bash(command="echo host-side")
    assert "host-side" in out


def test_swebench_verify_is_ungraded_not_local_pytest(tmp_path):
    inst = swebench.to_instance(FAKE_RECORD, cache_dir=tmp_path)
    v = inst.verify()  # must not run pytest at all -- instant, explicit
    assert v.passed is False
    assert "ungraded" in v.details.lower()
    assert "eval.official" in v.details
