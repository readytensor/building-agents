"""The `swebench` provider: SWE-bench Verified instances.

Loads the 500-instance SWE-bench Verified dataset (metadata only, ~25 MB) and
maps each record into the shared Instance shape. The target repo is cloned
lazily -- only for instances actually sampled -- and cached under eval/cache/
keyed by repo + base commit, so repeat runs reuse the checkout.

Scoring here is LOCAL, best-effort grading: apply the instance's held-out
test_patch (the gold tests, which the agent never sees), then run the
FAIL_TO_PASS / PASS_TO_PASS node ids with pytest in the working copy. This
requires the repo's dependencies to be importable in the current environment
and is NOT the official SWE-bench Docker grading; treat results as indicative.
"""
import json
import subprocess
from pathlib import Path

from eval.scoring import score_pytest
from eval.targets import Instance, Verdict

# Where lazy clones live: eval/cache/<org__repo>/<base_commit>/ (gitignored).
CACHE_DIR = Path(__file__).resolve().parents[1] / "cache"

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


def clone_at_commit(url: str, commit: str, dest: Path) -> Path:
    """Clone `url` and check out `commit` at dest. Idempotent: an existing
    checkout (dest/.git present) is trusted as the cache hit."""
    if (dest / ".git").exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", "-q", url, str(dest)],
                   check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(dest), "checkout", "-q", commit],
                   check=True, capture_output=True, text=True)
    return dest


def make_local_scorer(test_patch: str):
    """A scorer that applies the held-out test patch, then runs the node ids.
    The patch is applied at scoring time (after the agent's diff is captured),
    so the agent never sees the gold tests and the model patch stays clean."""
    def scorer(repo_dir: Path, fail_to_pass: list, pass_to_pass: list) -> Verdict:
        note = "LOCAL grading (test_patch applied locally; not official SWE-bench Docker grading)."
        if test_patch:
            apply = subprocess.run(
                ["git", "-C", str(repo_dir), "apply", "--whitespace=nowarn", "-"],
                input=test_patch, capture_output=True, text=True,
            )
            if apply.returncode != 0:
                return Verdict(
                    fail_to_pass={"passed": [], "failed": list(fail_to_pass)},
                    pass_to_pass={"passed": [], "failed": list(pass_to_pass)},
                    details=f"{note}\ntest_patch failed to apply:\n{apply.stderr[-1500:]}",
                )
        v = score_pytest(repo_dir, fail_to_pass, pass_to_pass)
        v.details = f"{note}\n{v.details}"
        return v
    return scorer


def to_instance(record: dict, cache_dir: Path = CACHE_DIR) -> Instance:
    """Map one Verified record to an Instance. FAIL_TO_PASS / PASS_TO_PASS come
    as JSON-encoded string lists in the dataset. The clone is deferred to
    prepare(), so building 500 Instances stays free."""
    repo = record["repo"]                      # e.g. "pallets/flask"
    commit = record["base_commit"]
    repo_dir = Path(cache_dir) / repo.replace("/", "__") / commit
    url = f"https://github.com/{repo}.git"
    return Instance(
        id=record["instance_id"],
        problem_statement=record["problem_statement"],
        repo_dir=repo_dir,
        fail_to_pass=json.loads(record["FAIL_TO_PASS"]),
        pass_to_pass=json.loads(record["PASS_TO_PASS"]),
        scorer=make_local_scorer(record.get("test_patch", "")),
        prepare=lambda: clone_at_commit(url, commit, repo_dir),
    )


def get_instances() -> list:
    """Provider entry point used by the CLI: all 500 Verified instances,
    clone-on-demand."""
    if _load_dataset_records is None:  # test seam for the no-datasets path
        raise RuntimeError("pip install datasets")
    records = _load_dataset_records()
    return [to_instance(r) for r in records]
