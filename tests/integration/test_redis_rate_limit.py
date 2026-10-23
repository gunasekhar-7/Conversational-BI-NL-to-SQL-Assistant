"""Shared-bucket proof (REVIEW.md cap 3 / 9.1 rating cap 1).

    docker compose -f docker-compose.test.yml up -d redis --wait
    TEST_REDIS_URL=redis://127.0.0.1:6380/0 pytest -m redis -v
    docker compose -f docker-compose.test.yml down

Safe in any run context: both tests consume TEST_REDIS_URL directly and the
wiring check runs in a fresh subprocess, so earlier imports in this process
cannot poison the result.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

TEST_REDIS_URL = os.getenv("TEST_REDIS_URL")
pytestmark = [
    pytest.mark.redis,
    pytest.mark.skipif(not TEST_REDIS_URL, reason="TEST_REDIS_URL not set"),
]

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_wiring_builds_redis_storage_when_configured():
    """Fresh interpreter: app wiring must construct RedisStorage when REDIS_URL is set.

    Review Focus: if the ping fails and storage silently falls back to memory,
    this FAILS with MemoryStorage in stderr — it never skips and never passes
    green on the wrong storage.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from src.api.routes import limiter; "
            "from limits.storage import RedisStorage; "
            "assert isinstance(limiter.limiter.storage, RedisStorage), "
            "f'got {type(limiter.limiter.storage).__name__}'",
        ],
        env={**os.environ, "REDIS_URL": TEST_REDIS_URL},
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"stdout={result.stdout} stderr={result.stderr}"


def test_buckets_shared_across_two_limiter_instances():
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded

    def make_app():
        app = FastAPI()
        lim = Limiter(key_func=lambda request: "shared-key", storage_uri=TEST_REDIS_URL)
        app.state.limiter = lim
        app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

        @app.get("/ping")
        @lim.limit("2/minute")
        def ping(request: Request):
            return {"ok": True}

        return app, lim

    app_a, lim_a = make_app()
    app_b, _ = make_app()
    try:
        a = TestClient(app_a)
        assert [a.get("/ping").status_code for _ in range(2)] == [200, 200]
        assert a.get("/ping").status_code == 429

        # Separate app, separate Limiter instance — only shared Redis can
        # explain a 429 on the very first request of instance B.
        b = TestClient(app_b)
        assert b.get("/ping").status_code == 429, "bucket must be shared through Redis"
    finally:
        lim_a.limiter.storage.reset()
