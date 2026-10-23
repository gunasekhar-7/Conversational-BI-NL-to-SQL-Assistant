import hashlib
import threading
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session
from src.db.session import get_db, engine as default_engine
from src.db.schema_inspector import inspect_schema, format_schema_for_prompt
from src.core.nl_to_sql import NLToSQL
from src.core.query_executor import execute_query, suggest_chart_type, dataframe_to_records
from src.config import settings
from src.api.schemas import QueryRequest, QueryResponse, SchemaResponse, HealthResponse
from src.api.auth import is_valid_api_key, require_api_key

router = APIRouter()

SCHEMA_TTL_SECONDS = 60.0


def rate_limit_key(request: Request) -> str:
    """Bucket requests by API key when valid, else by client address.

    The key is hashed so it never appears in memory dumps or logs as the
    bucket identifier. Only *valid* keys get their own bucket: an attacker
    cycling forged keys would otherwise mint one bucket per guess (unbounded
    memory); forged and anonymous callers share one per-IP bucket and are
    rejected later by require_api_key anyway.
    """
    api_key = request.headers.get("X-API-Key")
    if api_key and is_valid_api_key(api_key):
        digest = hashlib.sha256(api_key.encode()).hexdigest()[:32]
        return f"key:{digest}"
    return f"ip:{get_remote_address(request)}"


limiter = Limiter(key_func=rate_limit_key)


class SchemaCache:
    """Thread-safe TTL cache for the introspected database schema.

    Hitting information_schema on every /query is a pointless round-trip on
    a hot path; the schema only changes when someone migrates, so a short TTL
    is enough. The lock serializes fetches so concurrent cold requests pay for
    one inspection, not N. A failed inspection is never cached — a transient
    DB error must not pin a broken result for the whole TTL window.
    """

    def __init__(self, ttl_seconds=SCHEMA_TTL_SECONDS, fetch=None, clock=time.monotonic):
        self.ttl_seconds = ttl_seconds
        # None means "look up routes.inspect_schema at call time" so tests can
        # monkeypatch the module attribute; an injected fetch is used verbatim.
        self._fetch = fetch
        self._clock = clock
        self._lock = threading.Lock()
        self._schema = None
        self._fetched_at = 0.0

    def get(self, engine) -> dict:
        with self._lock:
            now = self._clock()
            if self._schema is not None and (now - self._fetched_at) < self.ttl_seconds:
                return self._schema
            fetch = self._fetch if self._fetch is not None else inspect_schema
            schema = fetch(engine)
            self._schema = schema
            self._fetched_at = now
            return schema


def get_engine() -> Engine:
    """The application engine, overridable via dependency_overrides."""
    return default_engine


def get_schema_cache(request: Request) -> SchemaCache:
    """The shared schema cache from app.state, created in the lifespan handler."""
    cache = getattr(request.app.state, "schema_cache", None)
    if cache is None:
        # Not started via lifespan (bare TestClient): create rather than fail.
        cache = SchemaCache()
        request.app.state.schema_cache = cache
    return cache


def get_nl_to_sql(request: Request) -> NLToSQL:
    """The LLM engine initialized once in the lifespan handler.

    Reading it from app.state removes the module-global TOCTOU race the old
    lazy singleton had: two concurrent first requests could both pass the
    None check and construct two engines.
    """
    engine = getattr(request.app.state, "nl_engine", None)
    if engine is None:
        detail = getattr(request.app.state, "nl_engine_error", None) or (
            "LLM engine not initialized. Server may still be starting up."
        )
        raise HTTPException(status_code=503, detail=detail)
    return engine


@router.get("/health", response_model=HealthResponse)
def health_check(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception:
        db_status = "disconnected"

    return HealthResponse(
        status="ok",
        database=db_status,
    )


@router.get("/schema", response_model=SchemaResponse, dependencies=[Depends(require_api_key)])
def get_schema(
    engine: Engine = Depends(get_engine),
    cache: SchemaCache = Depends(get_schema_cache),
):
    schema = cache.get(engine)
    return SchemaResponse(schema=schema)


@router.post("/query", response_model=QueryResponse, dependencies=[Depends(require_api_key)])
# A leaked API key must not be able to drain the Groq quota until it is
# noticed (REVIEW.md I-04): the LLM-backed endpoint is throttled per valid
# key, tunable via QUERY_RATE_LIMIT (read at process start).
@limiter.limit(settings.query_rate_limit)
def query_endpoint(
    payload: QueryRequest,
    request: Request,
    db: Session = Depends(get_db),
    engine: Engine = Depends(get_engine),
    cache: SchemaCache = Depends(get_schema_cache),
    nl_engine: NLToSQL = Depends(get_nl_to_sql),
):
    # `request` must be named exactly that: slowapi's decorator locates the
    # starlette Request by parameter name to evaluate the rate limit.
    schema = cache.get(engine)
    schema_desc = format_schema_for_prompt(schema)

    try:
        sql = nl_engine.generate_sql(payload.question, schema_desc)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"SQL generation failed: {str(e)}")

    df, error = execute_query(sql, db)

    if error:
        return QueryResponse(
            sql=sql,
            results=[],
            columns=[],
            row_count=0,
            error=error,
        )

    records = dataframe_to_records(df)
    chart_suggestion = suggest_chart_type(df)

    explanation = None
    if payload.explain:
        try:
            explanation = nl_engine.explain(payload.question, sql, schema_desc)
        except Exception:
            # The explanation is a nicety; a failure here must not fail the query.
            explanation = None

    return QueryResponse(
        sql=sql,
        results=records,
        columns=list(df.columns),
        row_count=len(records),
        chart_suggestion=chart_suggestion,
        explanation=explanation,
    )
