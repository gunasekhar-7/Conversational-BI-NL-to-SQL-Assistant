import secrets

from fastapi import Header, HTTPException

from src.config import settings


def valid_api_keys() -> tuple[str, ...]:
    """All accepted API keys: the primary key plus any comma-separated extras."""
    extras = tuple(k.strip() for k in settings.api_keys.split(",") if k.strip())
    return (settings.api_key, *extras)


def is_valid_api_key(key: str) -> bool:
    """True when `key` matches any configured key, in constant time per candidate."""
    if not key:
        return False
    return any(secrets.compare_digest(key, candidate) for candidate in valid_api_keys())


def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    """Refuse requests that do not carry a valid API key.

    The SQL validator bounds *what* may run; this bounds *who* may ask. Without
    it the query and schema endpoints are an anonymous read path into every
    table the database user can see.
    """
    if not is_valid_api_key(x_api_key or ""):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
