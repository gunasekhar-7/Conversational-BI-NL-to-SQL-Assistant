import json
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from src.api.routes import router, SchemaCache, limiter
from src.core.nl_to_sql import NLToSQL

logger = logging.getLogger(__name__)


async def request_logging_middleware(request: Request, call_next):
    """Tag every request with an ID and log one structured line per request.

    The ID is echoed in the X-Request-ID response header (and honored from
    the caller when supplied, so a proxy chain can correlate traces). The log
    line is JSON so `jq`/log pipelines can parse it without a parser — the
    observability gap REVIEW.md I-08 called out.
    """
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    request.state.request_id = request_id
    start = time.perf_counter()

    try:
        response = await call_next(request)
    except Exception:
        duration_ms = round((time.perf_counter() - start) * 1000, 1)
        logger.exception(
            json.dumps({
                "event": "http_request",
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": 500,
                "duration_ms": duration_ms,
            })
        )
        raise

    duration_ms = round((time.perf_counter() - start) * 1000, 1)
    response.headers["X-Request-ID"] = request_id
    logger.info(
        json.dumps({
            "event": "http_request",
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": duration_ms,
        })
    )
    return response


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Build the shared engine and schema cache exactly once per process.

    Constructing NLToSQL here replaces the lazy module-global singleton: the
    old check-then-set ran outside any lock, so concurrent first requests
    could build two engines. A missing LLM key must not take the whole API
    down — health and schema stay usable — so it degrades to a 503 on /query.
    """
    try:
        app.state.nl_engine = NLToSQL()
    except ValueError as e:
        logger.warning("LLM engine unavailable: %s", e)
        app.state.nl_engine = None
        app.state.nl_engine_error = str(e)
    else:
        app.state.nl_engine_error = None

    app.state.schema_cache = SchemaCache()
    yield


app = FastAPI(
    title="NL-to-SQL Conversational BI Assistant",
    description="Convert natural language questions to SQL queries safely",
    version="1.0.0",
    lifespan=lifespan,
)

# slowapi expects the limiter on app state and a handler mapping
# RateLimitExceeded to a 429 response (REVIEW.md I-04).
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Registered as a plain call because the middleware function is defined above
# the app it decorates; behavior is identical to @app.middleware("http").
app.middleware("http")(request_logging_middleware)

app.include_router(router, prefix="/api")


@app.get("/")
def root():
    return {"message": "NL-to-SQL Assistant API", "docs": "/docs"}
