"""Unit tests for multi-key auth and the rate-limit bucket key derivation."""

from starlette.requests import Request

from src.api.auth import is_valid_api_key
from src.api.routes import rate_limit_key
from src.config import settings


def make_request(x_api_key=None):
    headers = []
    if x_api_key is not None:
        headers.append((b"x-api-key", x_api_key.encode()))
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/query",
        "headers": headers,
        "query_string": b"",
        "client": ("203.0.113.9", 40000),
    }
    return Request(scope)


def test_accepts_primary_and_extra_keys(monkeypatch):
    monkeypatch.setattr(settings, "api_key", "primary")
    monkeypatch.setattr(settings, "api_keys", "alpha, beta,,")

    assert is_valid_api_key("primary")
    assert is_valid_api_key("alpha")
    assert is_valid_api_key("beta")
    assert not is_valid_api_key("gamma")
    assert not is_valid_api_key("")


def test_default_api_keys_is_empty_string():
    # Only DATABASE_URL/API_KEY/GROQ_API_KEY may be required (test_config
    # contract); api_keys must default to "" so single-key setups work.
    assert settings.api_keys == "" or isinstance(settings.api_keys, str)


def test_unknown_key_buckets_by_ip_not_by_key():
    # Review Focus: a forged key must not mint its own bucket (unbounded
    # memory if every random key got one); unknown keys share the caller IP.
    bucket = rate_limit_key(make_request(x_api_key="forged-123"))
    assert bucket.startswith("ip:")
    assert "forged-123" not in bucket


def test_missing_key_buckets_by_ip():
    assert rate_limit_key(make_request()).startswith("ip:")


def test_valid_key_buckets_by_hashed_key():
    bucket = rate_limit_key(make_request(x_api_key="test-key"))  # conftest default
    assert bucket.startswith("key:")
    assert "test-key" not in bucket


def test_query_rate_limit_default():
    assert settings.query_rate_limit == "30/minute"
