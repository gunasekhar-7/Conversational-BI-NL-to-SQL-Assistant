import os

import httpx

API_BASE = os.environ.get("API_BASE", "http://localhost:8000/api")
API_KEY = os.environ.get("API_KEY", "")

EMPTY_RESPONSE = {"sql": "", "results": [], "columns": [], "row_count": 0}


def _headers() -> dict:
    return {"X-API-Key": API_KEY} if API_KEY else {}


def call_query_api(question: str, explain: bool = False) -> dict:
    try:
        response = httpx.post(
            f"{API_BASE}/query",
            json={"question": question, "explain": explain},
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


def call_schema_api() -> tuple[dict, str | None]:
    """Return (schema, error).

    An empty dict alone is ambiguous — the database may genuinely have no
    tables, or the API may be down — so failures come back as an actionable
    message instead of being swallowed (REVIEW.md W-05).
    """
    try:
        response = httpx.get(f"{API_BASE}/schema", headers=_headers(), timeout=10.0)
        response.raise_for_status()
    except httpx.ConnectError:
        return {}, (
            f"Could not load schema: can't reach the API at {API_BASE}. "
            "Start it with `uvicorn src.main:app`."
        )
    except httpx.TimeoutException:
        return {}, "Could not load schema: the API did not answer in time."
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        if status == 401:
            return {}, (
                "Could not load schema: the API rejected this request's key "
                "(HTTP 401). Set API_KEY to the same value the API uses, then "
                "restart Streamlit."
            )
        return {}, f"Could not load schema: the API returned {status}."
    except Exception as e:
        return {}, f"Could not load schema: {e}"

    return response.json().get("schema", {}), None
