"""Postmortem telemetry: every tool-call record carries the tail of what the
tool RETURNED (a miss is often explained by the output the model saw), on both
the host and container dispatch paths."""


def test_host_tool_records_result_tail(monkeypatch):
    import eval.agent as agent
    import tools  # Ep 5's module, on sys.path via eval.agent
    from eval import container
    monkeypatch.setattr(container, "ACTIVE", None)
    monkeypatch.setattr(tools, "TOOL_CALLS", [])

    @tools.tool("echo for the test")
    def echo(text: str) -> str:
        return "R" * 600

    out = agent._call_tool({"echo": echo}, "echo", {"text": "hi"})
    assert out == "R" * 600
    record = tools.TOOL_CALLS[-1]
    assert record["tool"] == "echo"
    assert record["result_tail"] == "R" * 500  # tail only, capped


def test_container_tool_records_result_tail(monkeypatch):
    import eval.agent as agent
    import tools
    from eval import container
    monkeypatch.setattr(container, "ACTIVE", "cid1")
    monkeypatch.setattr(container, "fileop", lambda cid, op, kwargs: "container output")
    monkeypatch.setattr(tools, "TOOL_CALLS", [])

    out = agent._call_tool({}, "read", {"path": "f.py"})
    assert out == "container output"
    record = tools.TOOL_CALLS[-1]
    assert record["tool"] == "read"
    assert record["result_tail"] == "container output"
