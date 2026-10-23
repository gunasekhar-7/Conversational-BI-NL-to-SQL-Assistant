"""Integration tests for the Prometheus metrics endpoint (Task 6).

Review Focus #1 (label cardinality): random unmatched paths must collapse to
one `path="unmatched"` series. Review Focus (user content): no question or
SQL text may appear in the metrics body.
"""

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.api.routes import get_nl_to_sql
from src.db.session import get_db
from src.main import app

HEADERS = {"X-API-Key": "test-key"}


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _reset_rate_limits():
    from src.api.routes import limiter

    if hasattr(limiter, "reset"):
        limiter.reset()
    else:
        limiter.limiter.storage.reset()


@pytest.fixture(autouse=True)
def clean_rate_limit():
    _reset_rate_limits()
    yield
    _reset_rate_limits()


def make_mock_db(rows, columns):
    db = MagicMock()
    result = MagicMock()
    result.fetchall.return_value = rows
    result.keys.return_value = columns
    db.execute.return_value = result
    return db


def test_metrics_endpoint_exposes_request_series(client):
    client.get("/api/health")

    response = client.get("/api/metrics")

    assert response.status_code == 200
    assert "http_requests_total" in response.text
    assert "http_request_duration_seconds" in response.text


def test_random_404_paths_collapse_to_one_label(client):
    # Review Focus #1: 50 distinct bogus paths must not mint 50 label values.
    for i in range(50):
        response = client.get(f"/api/definitely-not-a-route-{i}")
        assert response.status_code == 404

    body = client.get("/api/metrics").text
    assert 'path="unmatched"' in body
    assert "definitely-not-a-route" not in body


def test_metrics_body_contains_no_user_content(client):
    mock_engine = MagicMock()
    mock_engine.generate_sql.return_value = "SELECT 1 as test"
    app.dependency_overrides[get_nl_to_sql] = lambda: mock_engine
    app.dependency_overrides[get_db] = lambda: make_mock_db([(1,)], ["test"])

    client.post(
        "/api/query", json={"question": "how many customers?"}, headers=HEADERS
    )

    body = client.get("/api/metrics").text
    assert "how many customers" not in body
    assert "SELECT" not in body


def test_metrics_endpoint_never_throttled(client):
    # Probes must never be blocked, same as /api/health.
    statuses = [client.get("/api/metrics").status_code for _ in range(35)]
    assert all(s == 200 for s in statuses)


def test_query_failures_increment_counters(client):
    mock_engine = MagicMock()
    mock_engine.generate_sql.side_effect = ValueError("Generated unsafe SQL: DROP")
    app.dependency_overrides[get_nl_to_sql] = lambda: mock_engine
    app.dependency_overrides[get_db] = lambda: make_mock_db([], [])

    response = client.post("/api/query", json={"question": "drop"}, headers=HEADERS)
    assert response.status_code == 400

    body = client.get("/api/metrics").text
    assert "sql_generation_failures_total" in body
