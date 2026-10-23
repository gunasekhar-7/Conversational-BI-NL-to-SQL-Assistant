"""call_schema_api must explain failures instead of returning {} silently (W-05)."""

from unittest.mock import MagicMock, patch

import httpx

from src.frontend.utils import call_schema_api


def test_schema_success_returns_schema_and_no_error():
    response = MagicMock()
    response.json.return_value = {"schema": {"customers": {}}}
    response.raise_for_status = MagicMock()

    with patch("src.frontend.utils.httpx.get", return_value=response):
        schema, error = call_schema_api()

    assert schema == {"customers": {}}
    assert error is None


def test_schema_connect_error_returns_actionable_message():
    with patch(
        "src.frontend.utils.httpx.get",
        side_effect=httpx.ConnectError("connection refused"),
    ):
        schema, error = call_schema_api()

    assert schema == {}
    assert error is not None
    # The message must tell the user what to do, not just fail silently.
    assert "uvicorn" in error or "API" in error


def test_schema_http_error_returns_status():
    response = MagicMock()
    response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "401", request=MagicMock(), response=MagicMock(status_code=401)
    )

    with patch("src.frontend.utils.httpx.get", return_value=response):
        schema, error = call_schema_api()

    assert schema == {}
    assert error is not None
    assert "401" in error


def test_schema_timeout_returns_error():
    with patch(
        "src.frontend.utils.httpx.get",
        side_effect=httpx.TimeoutException("timed out"),
    ):
        schema, error = call_schema_api()

    assert schema == {}
    assert error is not None
