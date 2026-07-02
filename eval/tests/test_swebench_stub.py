import pytest

from eval.targets import swebench


def test_get_instances_raises_not_implemented_with_guidance():
    with pytest.raises(NotImplementedError) as exc:
        swebench.get_instances()
    assert "deferred" in str(exc.value).lower()
