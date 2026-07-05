"""The system prompt is one shared artifact, kept as system_prompt.md files:
a common core in every episode, mechanism sections appearing as episodes
introduce them (Working plan in Ep 4, Skills in Ep 5), and the eval agent
adding exactly one eval-specific section (Orientation) on top of Ep 5.
This test is the drift guard: any copy edited alone fails here.
"""
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def _prompt(rel: str) -> str:
    return (_ROOT / rel / "system_prompt.md").read_text(encoding="utf-8")


def _sections(text: str) -> dict:
    """Split a prompt into {header: body}; the preamble/closing get key ''."""
    parts, key = {"": []}, ""
    for line in text.splitlines():
        if line.startswith("## "):
            key = line.strip()
            parts[key] = []
        else:
            parts[key].append(line)
    return {k: "\n".join(v).strip() for k, v in parts.items()}


def test_eval_prompt_adds_only_the_orientation_section():
    """Eval = Ep 5 plus ## Orientation (the injected repository map and the
    README-first mandate exist only in the eval harness for now; promotion
    to the episodes is a separate, later decision)."""
    ep5 = _sections(_prompt("episodes/05-skills"))
    ev = _sections(_prompt("eval"))
    for header, body in ep5.items():
        label = header or "(preamble)"
        assert ev[header] == body, f"eval drifted in {label}"
    assert set(ev) - set(ep5) == {"## Orientation"}
    # Section ORDER matters to the model: orientation is the start-of-task
    # routine, so it must precede everything else (dicts preserve file order).
    order = list(ev)
    assert order.index("## Orientation") < order.index("## Skills")


def test_early_episodes_share_the_same_core():
    assert (_prompt("episodes/01-loop")
            == _prompt("episodes/02-tools")
            == _prompt("episodes/03-compaction"))


def test_later_episodes_only_add_their_mechanism_section():
    core = _sections(_prompt("episodes/01-loop"))
    ep4 = _sections(_prompt("episodes/04-working-memory"))
    ep5 = _sections(_prompt("episodes/05-skills"))
    for header, body in core.items():
        if header:  # the '' preamble is checked below
            assert ep4[header] == body, f"ep4 drifted in {header}"
            assert ep5[header] == body, f"ep5 drifted in {header}"
    assert set(ep4) - set(core) == {"## Working plan"}
    assert set(ep5) - set(ep4) == {"## Skills"}
    assert ep5["## Working plan"] == ep4["## Working plan"]


def test_preamble_is_common():
    # The identity/task preamble (before the first ## section) must be
    # identical everywhere. The closing text rides inside the last section's
    # body, so the section comparison above already covers it.
    core = _sections(_prompt("episodes/01-loop"))[""]
    assert _sections(_prompt("episodes/04-working-memory"))[""] == core
    assert _sections(_prompt("episodes/05-skills"))[""] == core
