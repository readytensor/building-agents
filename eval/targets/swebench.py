"""The `swebench` provider: SWE-bench Verified instances.

Loads the 500-instance SWE-bench Verified dataset (metadata only, ~25 MB) and
maps each record into the shared Instance shape. The target repo is cloned
lazily -- only for instances actually sampled -- and cached under eval/cache/
keyed by repo + base commit, so repeat runs reuse the checkout.

These instances are deliberately NOT scored locally: running the repo's tests
against the host's (years-newer) dependency set produces noise, not signal.
The verdict of record is official SWE-bench Docker grading -- per sample via
run_eval --grade, or per batch via eval.official.
"""
import json
import subprocess
from pathlib import Path

from eval import container
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


def _ungraded_scorer(repo_dir: Path, fail_to_pass: list, pass_to_pass: list) -> Verdict:
    """SWE-bench instances are NOT scored locally: host-side pytest against a
    years-old dependency set produces noise, not signal (imports fail, warning
    filters differ). The verdict of record comes from official Docker grading.
    This returns instantly with an explicit pointer instead of a fake score."""
    return Verdict(details=(
        "Ungraded locally by design. Grade this batch officially with: "
        "python -m eval.official <batch_dir> --model-name <model>"
    ))


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
        scorer=_ungraded_scorer,
        prepare=lambda: clone_at_commit(url, commit, repo_dir),
        meta={"difficulty": record.get("difficulty", ""), "repo": repo},
        env_setup=lambda work_dir, iid=record["instance_id"]: _container_env(iid, work_dir),
    )


def _container_env(instance_id: str, work_dir: Path):
    """Start the instance's own container (agent bash runs in the repo's real
    environment); return the teardown that stops it."""
    cid = container.start(instance_id, work_dir)
    return lambda: container.stop(cid)


def get_instances() -> list:
    """Provider entry point used by the CLI: all 500 Verified instances,
    clone-on-demand."""
    if _load_dataset_records is None:  # test seam for the no-datasets path
        raise RuntimeError("pip install datasets")
    records = _load_dataset_records()
    return [to_instance(r) for r in records]
