from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.api.routes import get_nl_to_sql
from src.db.session import get_db
from src.main import app


@pytest.fixture
def client():
    test_client = TestClient(app)
    yield test_client
    app.dependency_overrides.clear()


def make_mock_db(rows, columns):
    db = MagicMock()
    result = MagicMock()
    result.fetchall.return_value = rows
    result.keys.return_value = columns
    db.execute.return_value = result
    return db


def test_health_endpoint(client):
    app.dependency_overrides[get_db] = lambda: make_mock_db([], [])

    response = client.get("/api/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["database"] == "connected"


def test_query_endpoint_success(client):
    mock_engine = MagicMock()
    mock_engine.generate_sql.return_value = "SELECT 1 as test"
    app.dependency_overrides[get_nl_to_sql] = lambda: mock_engine
    app.dependency_overrides[get_db] = lambda: make_mock_db([(1,)], ["test"])

    response = client.post("/api/query", json={"question": "test"})

    assert response.status_code == 200
    data = response.json()
    assert data["sql"] == "SELECT 1 as test"
    assert data["row_count"] == 1
    assert data["results"] == [{"test": 1}]
    mock_engine.generate_sql.assert_called_once()


def test_query_endpoint_unsafe_sql_rejected(client):
    mock_engine = MagicMock()
    mock_engine.generate_sql.side_effect = ValueError("Generated unsafe SQL: Forbidden keyword: DROP")
    app.dependency_overrides[get_nl_to_sql] = lambda: mock_engine
    app.dependency_overrides[get_db] = lambda: make_mock_db([], [])

    response = client.post("/api/query", json={"question": "drop everything"})

    assert response.status_code == 400
    assert "unsafe" in response.json()["detail"].lower()