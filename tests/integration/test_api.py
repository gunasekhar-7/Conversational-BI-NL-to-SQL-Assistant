from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from src.main import app


client = TestClient(app)


def test_health_endpoint():
    with patch('src.api.routes.get_db') as mock_get_db:
        mock_db = MagicMock()
        mock_db.execute.return_value = MagicMock()
        mock_get_db.return_value = mock_db

        response = client.get("/api/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"


def test_query_endpoint_success():
    with patch('src.api.routes.get_nl_to_sql') as mock_nl, \
         patch('src.api.routes.get_db') as mock_get_db, \
         patch('src.api.routes.inspect_schema') as mock_inspect:

        mock_inspect.return_value = {"customers": {"columns": [], "primary_key": [], "foreign_keys": []}}

        mock_nl_instance = MagicMock()
        mock_nl_instance.generate_sql.return_value = "SELECT 1 as test"
        mock_nl.return_value = mock_nl_instance

        mock_result = MagicMock()
        mock_result.fetchall.return_value = [(1,)]
        mock_result.keys.return_value = ['test']
        mock_db = MagicMock()
        mock_db.execute.return_value = mock_result
        mock_get_db.return_value = mock_db

        response = client.post("/api/query", json={"question": "test"})

        assert response.status_code == 200
        data = response.json()
        assert data["sql"] == "SELECT 1 as test"
        assert data["row_count"] == 1


def test_query_endpoint_unsafe_sql_rejected():
    with patch('src.api.routes.get_nl_to_sql') as mock_nl, \
         patch('src.api.routes.get_db') as mock_get_db, \
         patch('src.api.routes.inspect_schema') as mock_inspect:

        mock_inspect.return_value = {}

        mock_nl_instance = MagicMock()
        mock_nl_instance.generate_sql.side_effect = ValueError("Generated unsafe SQL")
        mock_nl.return_value = mock_nl_instance

        response = client.post("/api/query", json={"question": "test"})

        assert response.status_code == 400