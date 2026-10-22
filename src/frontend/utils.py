import httpx
import streamlit as st

API_BASE = "http://localhost:8000/api"


def call_query_api(question: str) -> dict:
    try:
        response = httpx.post(
            f"{API_BASE}/query",
            json={"question": question},
            timeout=30.0,
        )
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as e:
        return {"error": f"API error: {e.response.status_code}", "sql": "", "results": [], "columns": [], "row_count": 0}
    except Exception as e:
        return {"error": f"Connection error: {str(e)}", "sql": "", "results": [], "columns": [], "row_count": 0}


def call_schema_api() -> dict:
    try:
        response = httpx.get(f"{API_BASE}/schema", timeout=10.0)
        response.raise_for_status()
        return response.json().get("schema", {})
    except Exception:
        return {}