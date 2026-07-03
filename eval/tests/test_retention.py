from eval.results import apply_retention


def _seed_instance(batch_dir, label, passed):
    inst = batch_dir / label
    inst.mkdir(parents=True)
    (inst / "verify.json").write_text("{}")
    (inst / "diff.patch").write_text("x")
    (inst / "output.log").write_text("verbose")
    (inst / "metrics.json").write_text("{}")
    (inst / "tool_calls.jsonl").write_text("{}")
    (inst / "final_message.md").write_text("done")
    return {"inst_dir": str(inst), "passed": passed}


def test_failures_keep_gzipped_verbose_passes_drop_it(tmp_path):
    batch = tmp_path / "batch"
    ok = _seed_instance(batch, "ok", True)
    bad = _seed_instance(batch, "bad", False)
    apply_retention(batch, [ok, bad], keep="failures")

    # Passing instance: verbose gone, always-keep artifacts remain.
    assert not (batch / "ok" / "output.log").exists()
    assert not (batch / "ok" / "output.log.gz").exists()
    assert (batch / "ok" / "verify.json").exists()
    assert (batch / "ok" / "diff.patch").exists()

    # Failing instance: verbose gzipped.
    assert not (batch / "bad" / "output.log").exists()
    assert (batch / "bad" / "output.log.gz").exists()
    assert (batch / "bad" / "verify.json").exists()

    # metrics and the final message survive raw for BOTH outcomes: analysis
    # needs passed runs too (batch20 lost every resolved sample's telemetry).
    for label in ("ok", "bad"):
        assert (batch / label / "metrics.json").exists()
        assert (batch / label / "final_message.md").exists()


def test_keep_all_keeps_everything(tmp_path):
    batch = tmp_path / "batch"
    ok = _seed_instance(batch, "ok", True)
    apply_retention(batch, [ok], keep="all")
    assert (batch / "ok" / "output.log").exists()
