"""The `swebench` provider: SWE-bench Verified instances, scored in Docker.

Deferred by design. The Instance shape is shared, so implementing this later
means: load SWE-bench Verified from HuggingFace, materialize each repo at its
base_commit, and supply a Docker-based scorer in place of local pytest.
"""
from eval.targets import Instance  # noqa: F401  (kept so the shared type is the contract)


def get_instances():
    raise NotImplementedError(
        "The swebench provider is deferred. Use --source local for now."
    )
