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


@pytest.fixture
def client():
    test_client = TestClient(app)
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
