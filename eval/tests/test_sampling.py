from eval.sampling import sample


def _items(n):
    # Minimal stand-ins: sampling only needs an `id` attribute.
    class Stub:
        def __init__(self, id):
            self.id = id
    return [Stub(f"inst-{i}") for i in range(n)]


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
