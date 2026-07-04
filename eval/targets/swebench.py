"""The `swebench` provider: SWE-bench Verified instances.

Loads the 500-instance SWE-bench Verified dataset (metadata only, ~25 MB) and
maps each record into the shared Instance shape. There is no host checkout at
all: each instance's prebuilt Docker image already contains the repo at its
base commit -- installed, built, with the exact frozen dependency set -- so
the agent works directly on the container's /testbed (env_setup starts it),
and the diff leaves the container as text (capture) before teardown.

These instances are deliberately NOT scored locally: running the repo's tests
against the host's (years-newer) dependency set produces noise, not signal.
The verdict of record is official SWE-bench Docker grading -- per sample via
run_eval --grade, or per batch via eval.official.
"""
import json

from eval import container
from eval.targets import Instance, Verdict

DATASET = "princeton-nlp/SWE-bench_Verified"


def _load_dataset_records():
    """Load the Verified split via HuggingFace datasets (lazy import)."""
    try:
        from datasets import load_dataset
    except ImportError:
        raise RuntimeError(
            "The swebench provider needs the HuggingFace datasets package: "
            "pip install datasets"
        )
    return list(load_dataset(DATASET, split="test"))


def _ungraded_scorer(repo_dir, fail_to_pass: list, pass_to_pass: list) -> Verdict:
    """SWE-bench instances are NOT scored locally: host-side pytest against a
    years-old dependency set produces noise, not signal (imports fail, warning
    filters differ). The verdict of record comes from official Docker grading.
    This returns instantly with an explicit pointer instead of a fake score."""
    return Verdict(details=(
        "Ungraded locally by design. Grade this batch officially with: "
        "python -m eval.official <batch_dir> --model-name <model>"
    ))


def to_instance(record: dict) -> Instance:
    """Map one Verified record to an Instance. FAIL_TO_PASS / PASS_TO_PASS come
    as JSON-encoded string lists in the dataset. repo_dir is None: the working
    copy is the instance image's own /testbed, entered via env_setup."""
    return Instance(
        id=record["instance_id"],
        problem_statement=record["problem_statement"],
        repo_dir=None,
        fail_to_pass=json.loads(record["FAIL_TO_PASS"]),
        pass_to_pass=json.loads(record["PASS_TO_PASS"]),
        scorer=_ungraded_scorer,
        meta={"difficulty": record.get("difficulty", ""), "repo": record["repo"]},
        env_setup=lambda work_dir, iid=record["instance_id"]: _container_env(iid),
        # ACTIVE is safe here: the runner captures before teardown, and the
        # eval agent runs one instance at a time (documented in container.py).
        # base_commit pins the diff target so an in-container `git commit`
        # can't launder the agent's work into an empty patch.
        capture=lambda bc=record["base_commit"]: container.capture_diff(
            container.ACTIVE, base_commit=bc),
    )


def _container_env(instance_id: str):
    """Start the instance's own container (the agent's whole workspace); return
    the teardown that stops it."""
    cid = container.start(instance_id)
    return lambda: container.stop(cid)


def get_instances() -> list:
    """Provider entry point used by the CLI: all 500 Verified instances."""
    if _load_dataset_records is None:  # test seam for the no-datasets path
        raise RuntimeError("pip install datasets")
    records = _load_dataset_records()
    return [to_instance(r) for r in records]
