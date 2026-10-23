from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.routes import get_nl_to_sql
from src.db.session import get_db
from src.main import app


HEADERS = {"X-API-Key": "test-key"}


def _reset_rate_limits():
    """Clear slowapi's in-memory buckets so tests cannot leak into each other."""
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


@pytest.fixture
def client():
    # Context manager runs the lifespan handler, so app.state.nl_engine and
    # app.state.schema_cache are initialized exactly as they are under uvicorn.
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def real_db_override():
    """Yield a dependency override backed by a real in-memory database."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(bind=engine)

    def _get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    return _get_db


def make_mock_db(rows, columns):
    db = MagicMock()
    result = MagicMock()
    result.fetchall.return_value = rows
    result.keys.return_value = columns
    db.execute.return_value = result
    return db


def test_nl_engine_initialized_at_startup(client):
    from src.core.nl_to_sql import NLToSQL

    assert isinstance(client.app.state.nl_engine, NLToSQL)


def test_get_nl_to_sql_reads_app_state():
    from starlette.requests import Request
    from src.api.routes import get_nl_to_sql

    sentinel = object()
    app.state.nl_engine = sentinel
    scope = {"type": "http", "method": "GET", "path": "/", "headers": [], "query_string": b"", "app": app}

    assert get_nl_to_sql(Request(scope)) is sentinel


def test_schema_inspected_once_within_ttl(client, monkeypatch):
    calls = []

    def fake_inspect(engine):
        calls.append(engine)
        return {"customers": {"columns": [{"name": "id", "type": "INTEGER"}], "primary_key": ["id"], "foreign_keys": []}}

    monkeypatch.setattr("src.api.routes.inspect_schema", fake_inspect)

    first = client.get("/api/schema", headers=HEADERS)
    second = client.get("/api/schema", headers=HEADERS)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == first.json()
    assert len(calls) == 1, "schema must be inspected once per TTL window"


def test_engine_flows_through_dependency_injection(client, monkeypatch):
    from src.api.routes import get_engine

    fake_engine = MagicMock(name="engine")
    captured = []
    monkeypatch.setattr("src.api.routes.inspect_schema", lambda e: captured.append(e) or {})
    app.dependency_overrides[get_engine] = lambda: fake_engine

    response = client.get("/api/schema", headers=HEADERS)

    assert response.status_code == 200
    assert captured and captured[0] is fake_engine


def test_query_rate_limited_after_burst(client):
    mock_engine = MagicMock()
    mock_engine.generate_sql.return_value = "SELECT 1 as test"
    app.dependency_overrides[get_nl_to_sql] = lambda: mock_engine
    app.dependency_overrides[get_db] = lambda: make_mock_db([(1,)], ["test"])

    statuses = [
        client.post("/api/query", json={"question": "q"}, headers=HEADERS).status_code
        for _ in range(31)
    ]

    assert statuses[0] == 200, "first request must pass"
    assert statuses[-1] == 429, f"expected the 31st request to be throttled, got {statuses[-1]}"
    assert all(s == 429 for s in statuses[30:])


def test_rate_limit_bucket_is_per_api_key(client, monkeypatch):
    mock_engine = MagicMock()
    mock_engine.generate_sql.return_value = "SELECT 1 as test"
    app.dependency_overrides[get_nl_to_sql] = lambda: mock_engine
    app.dependency_overrides[get_db] = lambda: make_mock_db([(1,)], ["test"])

    # Exhaust the bucket for the default test key.
    for _ in range(31):
        last = client.post("/api/query", json={"question": "q"}, headers=HEADERS)
    assert last.status_code == 429

    # A different valid key gets its own bucket and must still succeed.
    from src.config import settings

    monkeypatch.setattr(settings, "api_key", "second-key")
    response = client.post(
        "/api/query",
        json={"question": "q"},
        headers={"X-API-Key": "second-key"},
    )
    assert response.status_code == 200


def test_health_stays_unthrottled(client, real_db_override):
    app.dependency_overrides[get_db] = real_db_override

    statuses = [client.get("/api/health").status_code for _ in range(35)]

    assert all(s == 200 for s in statuses), "liveness probes must never be throttled"


def test_health_endpoint(client, real_db_override):
    # Uses a real session so the connectivity probe (db.execute) actually runs;
    # a MagicMock here would assert "connected" no matter what the code does.
    app.dependency_overrides[get_db] = real_db_override

    response = client.get("/api/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["database"] == "connected"


def test_health_endpoint_reports_disconnected_on_error(client):
    broken_db = MagicMock()
    broken_db.execute.side_effect = RuntimeError("connection refused")
    app.dependency_overrides[get_db] = lambda: broken_db

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["database"] == "disconnected"


def test_health_stays_public_without_api_key(client, real_db_override):
    app.dependency_overrides[get_db] = real_db_override

    assert client.get("/api/health").status_code == 200


def test_extra_api_keys_from_settings_are_accepted(client, monkeypatch):
    mock_engine = MagicMock()
    mock_engine.generate_sql.return_value = "SELECT 1 as test"
    app.dependency_overrides[get_nl_to_sql] = lambda: mock_engine
    app.dependency_overrides[get_db] = lambda: make_mock_db([(1,)], ["test"])

    from src.config import settings

    monkeypatch.setattr(settings, "api_keys", "alpha")
    response = client.post(
        "/api/query",
        json={"question": "test"},
        headers={"X-API-Key": "alpha"},
    )
    assert response.status_code == 200


def test_query_requires_api_key(client):
    response = client.post("/api/query", json={"question": "how many customers?"})

    assert response.status_code == 401


def test_query_rejects_wrong_api_key(client):
    response = client.post(
        "/api/query",
        json={"question": "how many customers?"},
        headers={"X-API-Key": "not-the-key"},
    )

    assert response.status_code == 401


def test_schema_requires_api_key(client):
    assert client.get("/api/schema").status_code == 401


def test_query_rejects_empty_question(client):
    response = client.post(
        "/api/query", json={"question": "   "}, headers=HEADERS
    )

    assert response.status_code == 422


def test_query_rejects_overlong_question(client):
    response = client.post(
        "/api/query", json={"question": "x" * 2001}, headers=HEADERS
    )

    assert response.status_code == 422


def test_query_strips_question_whitespace(client):
    mock_engine = MagicMock()
    mock_engine.generate_sql.return_value = "SELECT 1 as test"
    app.dependency_overrides[get_nl_to_sql] = lambda: mock_engine
    app.dependency_overrides[get_db] = lambda: make_mock_db([(1,)], ["test"])

    response = client.post(
        "/api/query", json={"question": "  how many customers?  "}, headers=HEADERS
    )

    assert response.status_code == 200
    asked_question = mock_engine.generate_sql.call_args[0][0]
    assert asked_question == "how many customers?"


def test_query_endpoint_success(client):
    mock_engine = MagicMock()
    mock_engine.generate_sql.return_value = "SELECT 1 as test"
    app.dependency_overrides[get_nl_to_sql] = lambda: mock_engine
    app.dependency_overrides[get_db] = lambda: make_mock_db([(1,)], ["test"])

    response = client.post("/api/query", json={"question": "test"}, headers=HEADERS)

    assert response.status_code == 200
    data = response.json()
    assert data["sql"] == "SELECT 1 as test"
    assert data["row_count"] == 1
    assert data["results"] == [{"test": 1}]
    mock_engine.generate_sql.assert_called_once()


def test_query_endpoint_unsafe_sql_rejected(client):
    mock_engine = MagicMock()
    mock_engine.generate_sql.side_effect = ValueError(
        "Generated unsafe SQL: Forbidden keyword: DROP"
    )
    app.dependency_overrides[get_nl_to_sql] = lambda: mock_engine
    app.dependency_overrides[get_db] = lambda: make_mock_db([], [])

    response = client.post(
        "/api/query", json={"question": "drop everything"}, headers=HEADERS
    )

    assert response.status_code == 400
    assert "unsafe" in response.json()["detail"].lower()


def test_query_endpoint_explain_returns_explanation(client):
    mock_engine = MagicMock()
    mock_engine.generate_sql.return_value = "SELECT 1 as test"
    mock_engine.explain.return_value = "Returns a single constant column named test."
    app.dependency_overrides[get_nl_to_sql] = lambda: mock_engine
    app.dependency_overrides[get_db] = lambda: make_mock_db([(1,)], ["test"])

    response = client.post(
        "/api/query", json={"question": "test", "explain": True}, headers=HEADERS
    )

    assert response.status_code == 200
    data = response.json()
    assert data["explanation"] == "Returns a single constant column named test."
    mock_engine.explain.assert_called_once()


def test_query_endpoint_explain_false_skips_explanation(client):
    mock_engine = MagicMock()
    mock_engine.generate_sql.return_value = "SELECT 1 as test"
    app.dependency_overrides[get_nl_to_sql] = lambda: mock_engine
    app.dependency_overrides[get_db] = lambda: make_mock_db([(1,)], ["test"])

    response = client.post(
        "/api/query", json={"question": "test", "explain": False}, headers=HEADERS
    )

    assert response.status_code == 200
    assert response.json()["explanation"] is None
    mock_engine.explain.assert_not_called()
