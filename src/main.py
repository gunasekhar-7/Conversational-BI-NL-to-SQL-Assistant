import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from src.api.routes import router, SchemaCache
from src.core.nl_to_sql import NLToSQL

logger = logging.getLogger(__name__)


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

app.include_router(router, prefix="/api")


@app.get("/")
def root():
    return {"message": "NL-to-SQL Assistant API", "docs": "/docs"}
