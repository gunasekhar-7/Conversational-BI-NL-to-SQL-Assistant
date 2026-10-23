import logging
import math
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session
from src.config import settings
from src.core.sql_validator import validate_sql
from typing import Tuple


logger = logging.getLogger(__name__)

__all__ = (
    "EXECUTION_ERROR",
    "bounded_query",
    "dataframe_to_records",
    "execute_query",
    "suggest_chart_type",
)

MAX_ROWS = 1000

EXECUTION_ERROR = "Query execution failed. See the server log for details."


def bounded_query(sql: str, limit: int = MAX_ROWS) -> str:
    """Wrap `sql` so the row cap cannot be removed by the query text.

    Appending ` LIMIT n` is unsafe: a trailing line comment swallows it
    (`SELECT ... -- note LIMIT 1000`). Wrapping the statement in a subselect
    puts the cap outside anything the query itself can comment out.
    """
    body = sql.strip().rstrip(";").rstrip()
    return f"SELECT * FROM (\n{body}\n) AS _capped LIMIT {limit}"


def execute_query(sql: str, db: Session) -> Tuple[pd.DataFrame, str]:
    is_safe, error = validate_sql(sql)
    if not is_safe:
        return pd.DataFrame(), error

    try:
        # W-06: connect_args sets statement_timeout at connection-open, but a
        # pooled connection's GUC can be changed mid-session by anything else
        # holding it. Re-assert the cap inside this transaction so it is in
        # force for exactly this query, and expires on commit/rollback.
        # SET LOCAL is Postgres-only; other dialects get the connect-args
        # behavior (or none) and must never see this statement.
        if db.bind.dialect.name == "postgresql":
            db.execute(
                text(f"SET LOCAL statement_timeout = {int(settings.statement_timeout_ms)}")
            )

        result = db.execute(text(bounded_query(sql)))
        rows = result.fetchall()
        columns = result.keys()

        return pd.DataFrame(rows, columns=columns), ""

    except Exception:
        # The driver message carries the executed SQL and table names; keep it
        # in the log rather than handing it to the caller.
        logger.exception("SQL execution failed")
        return pd.DataFrame(), EXECUTION_ERROR


def _json_finite(value):
    """Map non-finite floats to None so the payload is strict-JSON safe."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def dataframe_to_records(df: pd.DataFrame) -> list[dict]:
    """Serialize a frame to JSON-safe records.

    SQL NULLs become NaN in pandas and infinities can arrive from aggregates
    like 1/0; neither survives strict JSON encoding, so they become null.
    """
    records = df.astype(object).where(df.notnull(), None).to_dict(orient="records")
    return [{k: _json_finite(v) for k, v in row.items()} for row in records]


def suggest_chart_type(df: pd.DataFrame) -> str | None:
    """Pick a chart for a result frame, or None when nothing suits it.

    Contract:
      - no chart for an empty frame, fewer than two columns, or a frame with
        no numeric column (there is nothing to plot);
      - `line` when any column is datetime — a time series reads as a
        continuous line no matter how short or long it is (REVIEW.md I-03:
        row count alone must not imply continuity);
      - `scatter` when two numeric columns can be plotted against each other;
      - `bar` otherwise, with the categorical column as the axis — including
        high-row-count categorical results, which are categories, not series.

    Pie is never suggested automatically: a categorical total renders as a pie
    only when the user asks for it, so the frontend keeps it as an explicit
    choice rather than a guess.
    """
    if df.empty or len(df.columns) < 2:
        return None

    numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()

    if not numeric_cols:
        return None

    if len(df.select_dtypes(include=["datetime", "datetimetz"]).columns) > 0:
        return "line"

    if len(numeric_cols) >= 2:
        return "scatter"

    return "bar"
