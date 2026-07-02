"""Select which instances to run: pin one by id, or take a seeded random sample.

Seeded so a run is reproducible: the same (pool, n, seed) always yields the same
instances, and the seed is recorded in the batch manifest.
"""
import random

# CLI difficulty buckets -> the labels SWE-bench Verified's annotators used
# (estimated time-to-fix). "hard" spans both multi-hour buckets.
DIFFICULTY_LABELS = {
    "easy": {"<15 min fix"},
    "medium": {"15 min - 1 hour"},
    "hard": {"1-4 hours", ">4 hours"},
}


def filter_pool(instances, difficulty=None, repo=None):
    """Narrow the pool by provider metadata before sampling. Instances with no
    matching meta key simply don't match a filter."""
    pool = instances
    if difficulty is not None:
        labels = DIFFICULTY_LABELS[difficulty]
        pool = [i for i in pool if i.meta.get("difficulty") in labels]
    if repo is not None:
        pool = [i for i in pool if repo in i.meta.get("repo", "")]
    return pool


def sample(instances, n, seed, instance_id=None):
    """Return the instances to run.

    - instance_id set: return exactly that one instance (or empty if unknown).
    - otherwise: a seeded random sample of size min(n, len(pool)), order stable.
    """
    if instance_id is not None:
        return [i for i in instances if i.id == instance_id]
    pool = sorted(instances, key=lambda i: i.id)  # stable input order before seeding
    rng = random.Random(seed)
    k = min(n, len(pool))
    return rng.sample(pool, k)
