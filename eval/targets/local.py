"""The `local` provider: md2html instances scored by running pytest directly.

Each instance is an md2html feature/bug task defined by a spec: an id, the task
text, and the pytest node ids that define success (fail_to_pass) and must not
regress (pass_to_pass). All instances share one base md2html tree; the runner
materializes a fresh working copy per attempt.

Seeding real md2html tasks (their base trees + FAIL_TO_PASS sets) is done when
wiring the smoke run; the shape here is what matters for the harness.
"""
from pathlib import Path

from eval.scoring import score_pytest
from eval.targets import Instance

# The default md2html base tree, relative to the repo root. A concrete tree is
# wired in at smoke-test time; DEFAULT_SPECS below is seeded then too.
DEFAULT_BASE = Path("eval/fixtures/md2html")
DEFAULT_SPECS: list = []  # filled when real md2html tasks are seeded (see README)


def build_instances(base_dir=DEFAULT_BASE, specs=None) -> list:
    """Turn (base_dir, specs) into Instance objects. Raises on duplicate ids."""
    specs = DEFAULT_SPECS if specs is None else specs
    base = Path(base_dir)
    seen, instances = set(), []
    for spec in specs:
        if spec["id"] in seen:
            raise ValueError(f"duplicate instance id: {spec['id']}")
        seen.add(spec["id"])
        instances.append(Instance(
            id=spec["id"],
            problem_statement=spec["problem_statement"],
            repo_dir=base,
            fail_to_pass=spec["fail_to_pass"],
            pass_to_pass=spec["pass_to_pass"],
            scorer=score_pytest,
        ))
    return instances


def get_instances() -> list:
    """Provider entry point used by the CLI."""
    return build_instances()
