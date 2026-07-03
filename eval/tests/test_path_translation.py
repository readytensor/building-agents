"""The container roots the repo at /testbed; the file tools resolve paths on
the host. eval.agent translates between the two namespaces at the tool
boundary so paths copied out of container output (tracebacks, grep) work."""
from eval.agent import _host_path, _translating


def test_host_path_translates_testbed_prefix():
    assert _host_path("/testbed") == "."
    assert _host_path("/testbed/pkg/mod.py") == "pkg/mod.py"


def test_host_path_leaves_other_paths_alone():
    assert _host_path("pkg/mod.py") == "pkg/mod.py"        # relative: untouched
    assert _host_path("/etc/passwd") == "/etc/passwd"      # still caught by the sandbox check
    assert _host_path("/testbedX/f.py") == "/testbedX/f.py"  # prefix must be a whole segment


def test_translated_read_resolves_a_testbed_path(monkeypatch, tmp_path):
    import tools  # Ep 5's module, on sys.path via eval.agent
    monkeypatch.setattr(tools, "SANDBOX", tmp_path)
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "mod.py").write_text("x = 1\n", encoding="utf-8")
    read = _translating(tools.read)
    assert "x = 1" in read(path="/testbed/pkg/mod.py")


def test_translated_tool_keeps_name_schema_and_single_telemetry(monkeypatch, tmp_path):
    import tools
    monkeypatch.setattr(tools, "SANDBOX", tmp_path)
    monkeypatch.setattr(tools, "TOOL_CALLS", [])
    (tmp_path / "f.txt").write_text("hello\n", encoding="utf-8")
    read = _translating(tools.read)
    assert read.__name__ == "read"
    assert read.tool_definition == tools.read.tool_definition
    read(path="/testbed/f.txt")
    # One telemetry record (the @tool-wrapped original's), with the host path.
    assert len(tools.TOOL_CALLS) == 1
    assert tools.TOOL_CALLS[0]["args"]["path"] == "f.txt"
