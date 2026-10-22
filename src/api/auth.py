import secrets

from fastapi import Header, HTTPException

from src.config import settings


def require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None:
    """Refuse requests that do not carry the shared API key.

    The SQL validator bounds *what* may run; this bounds *who* may ask. Without
    it the query and schema endpoints are an anonymous read path into every
    table the database user can see.
    """
    if not x_api_key or not secrets.compare_digest(x_api_key, settings.api_key):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
