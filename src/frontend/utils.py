import os

import httpx

API_BASE = os.environ.get("API_BASE", "http://localhost:8000/api")
API_KEY = os.environ.get("API_KEY", "")

EMPTY_RESPONSE = {"sql": "", "results": [], "columns": [], "row_count": 0}


def _headers() -> dict:
    return {"X-API-Key": API_KEY} if API_KEY else {}


def call_query_api(question: str) -> dict:
    try:
        response = httpx.post(
            f"{API_BASE}/query",
            json={"question": question},
            headers=_headers(),
            timeout=30.0,
        )
    except httpx.ConnectError:
        return {
            **EMPTY_RESPONSE,
            "error": (
                f"Can't reach the API at {API_BASE}. "
                "Start it with `uvicorn src.main:app` and ask again."
            ),
        }
    except httpx.TimeoutException:
        return {
            **EMPTY_RESPONSE,
            "error": "The API did not answer in time. Try a narrower question.",
        }

    if response.status_code == 401:
        return {
            **EMPTY_RESPONSE,
            "error": (
                "The API rejected this request's key. Set API_KEY to the same "
                "value the API uses, then restart Streamlit."
            ),
        }

    if response.status_code >= 400:
        return {
            **EMPTY_RESPONSE,
            "error": (
                f"The API returned {response.status_code}. "
                "Check the API log for the underlying error."
            ),
        }

    return response.json()


def call_schema_api() -> dict:
    try:
        response = httpx.get(f"{API_BASE}/schema", headers=_headers(), timeout=10.0)
        response.raise_for_status()
        return response.json().get("schema", {})
    except Exception:
        return {}
