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


def _allocate(n, sizes):
    """Split n across buckets in proportion to their sizes, using largest-
    remainder rounding so the counts always sum to n (capped at the pool)."""
    total = sum(sizes.values())
    n = min(n, total)
    exact = {name: n * size / total for name, size in sizes.items()}
    counts = {name: int(exact[name]) for name in sizes}
    while sum(counts.values()) < n:
        # Hand leftover slots to the buckets rounding lost the most from,
        # skipping any bucket already at its full size.
        open_buckets = [b for b in sizes if counts[b] < sizes[b]]
        counts[max(open_buckets, key=lambda b: (exact[b] - counts[b], b))] += 1
    return counts


def stratified_sample(instances, n, seed):
    """A seeded sample spread across the difficulty buckets in proportion to
    their share of the pool, so a small n still mirrors the pool's mix instead
    of drifting toward whichever bucket chance favors."""
    buckets = {
        name: sorted((i for i in instances if i.meta.get("difficulty") in labels),
                     key=lambda i: i.id)
        for name, labels in DIFFICULTY_LABELS.items()
    }
    buckets = {name: pool for name, pool in buckets.items() if pool}
    if not buckets:
        raise ValueError("stratified sampling needs difficulty metadata on the pool")
    counts = _allocate(n, {name: len(pool) for name, pool in buckets.items()})
    picked = []
    for name in sorted(buckets):
        # One RNG stream per bucket: a bucket's picks depend only on the seed,
        # not on what the other buckets contain.
        rng = random.Random(f"{seed}:{name}")
        picked += rng.sample(buckets[name], counts[name])
    return picked


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
