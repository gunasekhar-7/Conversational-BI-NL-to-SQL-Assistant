import logging
import math
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session
from src.core.sql_validator import validate_sql
from typing import Tuple


logger = logging.getLogger(__name__)

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
      - `line` once there are more than 20 rows, where a series reads better
        than bars;
      - `scatter` when two numeric columns can be plotted against each other;
      - `bar` otherwise, with the categorical column as the axis.

    Pie is never suggested automatically: a categorical total renders as a pie
    only when the user asks for it, so the frontend keeps it as an explicit
    choice rather than a guess.
    """
    if df.empty or len(df.columns) < 2:
        return None

    numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()

    if not numeric_cols:
        return None

    if len(df) > 20:
        return "line"

    if len(numeric_cols) >= 2:
        return "scatter"

    return "bar"
