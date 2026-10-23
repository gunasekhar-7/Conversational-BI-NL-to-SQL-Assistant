from unittest.mock import MagicMock

import pytest

from src.api.routes import SchemaCache


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_returns_cached_data_within_ttl():
    clock = FakeClock()
    engine = MagicMock()
    fetch = MagicMock(return_value={"a": 1})
    cache = SchemaCache(ttl_seconds=60.0, fetch=fetch, clock=clock)

    first = cache.get(engine)
    clock.now += 59.0
    second = cache.get(engine)

    assert first == second == {"a": 1}
    assert fetch.call_count == 1


def test_refetches_after_ttl_expires():
    clock = FakeClock()
    engine = MagicMock()
    fetch = MagicMock(side_effect=[{"a": 1}, {"a": 2}])
    cache = SchemaCache(ttl_seconds=60.0, fetch=fetch, clock=clock)

    first = cache.get(engine)
    clock.now += 61.0
    second = cache.get(engine)

    assert first == {"a": 1}
    assert second == {"a": 2}
    assert fetch.call_count == 2


def test_failed_fetch_is_not_cached():
    engine = MagicMock()
    fetch = MagicMock(side_effect=RuntimeError("db down"))
    cache = SchemaCache(ttl_seconds=60.0, fetch=fetch, clock=FakeClock())

    with pytest.raises(RuntimeError):
        cache.get(engine)
    with pytest.raises(RuntimeError):
        cache.get(engine)

    assert fetch.call_count == 2, "a failed inspection must not be cached"
