"""Request IDs and one structured log line per request (REVIEW.md I-08)."""

import json
import logging

import pytest
from fastapi.testclient import TestClient

from src.main import app

HEADERS = {"X-API-Key": "test-key"}


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_response_carries_request_id_header(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.headers.get("X-Request-ID"), "every response must carry a request ID"


def test_incoming_request_id_is_echoed(client):
    response = client.get("/api/health", headers={"X-Request-ID": "trace-me-123"})

    assert response.headers["X-Request-ID"] == "trace-me-123"


def test_structured_log_line_emitted(client, caplog):
    with caplog.at_level(logging.INFO, logger="src.main"):
        client.get("/api/health")

    request_logs = [
        json.loads(r.message)
        for r in caplog.records
        if r.name == "src.main" and r.message.startswith("{")
    ]

    assert request_logs, "one structured JSON line per request is expected"
    entry = request_logs[-1]
    assert entry["event"] == "http_request"
    assert entry["method"] == "GET"
    assert entry["path"] == "/api/health"
    assert entry["status"] == 200
    assert "duration_ms" in entry
    assert entry["request_id"]
