import pytest

from eval.sampling import sample, stratified_sample


def _items(n):
    # Minimal stand-ins: sampling only needs an `id` attribute.
    class Stub:
        def __init__(self, id):
            self.id = id
    return [Stub(f"inst-{i}") for i in range(n)]


def _labeled_items(easy=0, medium=0, hard=0):
    # Stand-ins carrying the difficulty metadata the swebench provider sets.
    class Stub:
        def __init__(self, id, label):
            self.id = id
            self.meta = {"difficulty": label}
    pool = []
    for label, count in (("<15 min fix", easy), ("15 min - 1 hour", medium),
                         ("1-4 hours", hard)):
        pool += [Stub(f"{label}-{i}", label) for i in range(count)]
    return pool


def _bucket_counts(picked):
    counts = {"easy": 0, "medium": 0, "hard": 0}
    for i in picked:
        label = i.meta["difficulty"]
        key = {"<15 min fix": "easy", "15 min - 1 hour": "medium"}.get(label, "hard")
        counts[key] += 1
    return counts


def test_pin_by_id_returns_just_that_instance():
    items = _items(5)
    picked = sample(items, n=3, seed=0, instance_id="inst-2")
    assert [i.id for i in picked] == ["inst-2"]


def test_seeded_sampling_is_reproducible():
    items = _items(20)
    a = [i.id for i in sample(items, n=5, seed=42)]
    b = [i.id for i in sample(items, n=5, seed=42)]
    assert a == b
    assert len(a) == 5


def test_different_seed_can_differ():
    items = _items(20)
    a = [i.id for i in sample(items, n=5, seed=1)]
    b = [i.id for i in sample(items, n=5, seed=2)]
    assert a != b  # overwhelmingly likely for 5-of-20


def test_n_larger_than_pool_returns_whole_pool():
    items = _items(3)
    assert len(sample(items, n=10, seed=0)) == 3


def test_stratified_matches_bucket_proportions():
    # Pool is 50% easy / 40% medium / 10% hard; n=10 should mirror it exactly.
    items = _labeled_items(easy=10, medium=8, hard=2)
    picked = stratified_sample(items, n=10, seed=0)
    assert _bucket_counts(picked) == {"easy": 5, "medium": 4, "hard": 1}


def test_stratified_is_reproducible():
    items = _labeled_items(easy=10, medium=8, hard=2)
    a = [i.id for i in stratified_sample(items, n=10, seed=42)]
    b = [i.id for i in stratified_sample(items, n=10, seed=42)]
    assert a == b
    assert len(a) == 10


def test_stratified_n_larger_than_pool_returns_whole_pool():
    items = _labeled_items(easy=2, medium=1, hard=1)
    assert len(stratified_sample(items, n=10, seed=0)) == 4


def test_stratified_requires_difficulty_metadata():
    # Pool without difficulty labels (e.g. the local provider): fail loudly
    # rather than silently sampling from nothing.
    class Stub:
        def __init__(self, id):
            self.id = id
            self.meta = {}
    items = [Stub(f"inst-{i}") for i in range(5)]
    with pytest.raises(ValueError, match="difficulty metadata"):
        stratified_sample(items, n=3, seed=0)
