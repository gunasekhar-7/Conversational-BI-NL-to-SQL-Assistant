"""Prometheus metrics for the API (REVIEW.md I-08 follow-through, cap 4).

Label discipline: `path` is always a route template (e.g. "/api/query") or
the literal "unmatched" — never a raw request path — so a client requesting
thousands of bogus URLs cannot explode metric cardinality. Question text and
SQL never appear here; only method, route template, status, and durations.
"""

from fastapi import Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)

REGISTRY = CollectorRegistry()

HTTP_REQUESTS = Counter(
    "http_requests_total",
    "Requests",
    ["method", "path", "status"],
    registry=REGISTRY,
)

HTTP_LATENCY = Histogram(
    "http_request_duration_seconds",
    "Request latency",
    ["method", "path"],
    registry=REGISTRY,
)

SQL_GENERATION_FAILURES = Counter(
    "sql_generation_failures_total",
    "LLM SQL generation failures",
    registry=REGISTRY,
)

QUERY_FAILURES = Counter(
    "query_execution_failures_total",
    "Rejected or failed queries",
    registry=REGISTRY,
)


def observe_request(method: str, path: str, status: int, duration_seconds: float) -> None:
    HTTP_REQUESTS.labels(method=method, path=path, status=str(status)).inc()
    HTTP_LATENCY.labels(method=method, path=path).observe(duration_seconds)


def metrics_response() -> Response:
    return Response(content=generate_latest(REGISTRY), headers={"Content-Type": CONTENT_TYPE_LATEST})
