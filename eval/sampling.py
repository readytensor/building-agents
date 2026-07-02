"""Select which instances to run: pin one by id, or take a seeded random sample.

Seeded so a run is reproducible: the same (pool, n, seed) always yields the same
instances, and the seed is recorded in the batch manifest.
"""
import random


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
