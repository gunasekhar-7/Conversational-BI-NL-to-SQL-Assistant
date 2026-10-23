"""Unit tests for rate-limiter storage selection (Task 5).

The limiter must share buckets across workers when Redis is configured, and
must never take the API down when Redis is not (REVIEW.md cap 3 / Review
Focus #2): unreachable Redis at startup degrades to per-process memory.
"""

from src.api.routes import build_storage_uri


def test_defaults_to_memory_when_no_redis_url():
    assert build_storage_uri(None) == "memory://"


def test_uses_redis_when_reachable():
    uri = build_storage_uri("redis://localhost:6379/0", ping=lambda url: True)
    assert uri == "redis://localhost:6379/0"


def test_falls_back_to_memory_when_redis_unreachable():
    uri = build_storage_uri("redis://localhost:6379/0", ping=lambda url: False)
    assert uri == "memory://"


def test_default_limiter_storage_is_memory_in_tests():
    # The default environment (no REDIS_URL) must construct an in-memory
    # limiter so the offline suite exercises the same storage as a
    # single-process dev run.
    from src.api.routes import limiter

    assert "MemoryStorage" in type(limiter.limiter.storage).__name__
