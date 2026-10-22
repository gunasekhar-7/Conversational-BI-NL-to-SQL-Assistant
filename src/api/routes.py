from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session
from src.db.session import get_db
from src.db.schema_inspector import inspect_schema, format_schema_for_prompt
from src.core.nl_to_sql import NLToSQL
from src.core.query_executor import execute_query, suggest_chart_type, dataframe_to_records
from src.api.schemas import QueryRequest, QueryResponse, SchemaResponse, HealthResponse
from src.api.auth import require_api_key

router = APIRouter()

_nl_to_sql_engine = None


def get_nl_to_sql() -> NLToSQL:
    global _nl_to_sql_engine
    if _nl_to_sql_engine is None:
        _nl_to_sql_engine = NLToSQL()
    return _nl_to_sql_engine


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
def get_schema(db: Session = Depends(get_db)):
    from src.db.session import engine
    schema = inspect_schema(engine)
    return SchemaResponse(schema=schema)


@router.post("/query", response_model=QueryResponse, dependencies=[Depends(require_api_key)])
def query_endpoint(
    request: QueryRequest,
    db: Session = Depends(get_db),
    nl_engine: NLToSQL = Depends(get_nl_to_sql),
):
    from src.db.session import engine
    schema = inspect_schema(engine)
    schema_desc = format_schema_for_prompt(schema)

    try:
        sql = nl_engine.generate_sql(request.question, schema_desc)
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

    return QueryResponse(
        sql=sql,
        results=records,
        columns=list(df.columns),
        row_count=len(records),
        chart_suggestion=chart_suggestion,
    )