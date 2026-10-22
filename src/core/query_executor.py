import pandas as pd
from sqlalchemy.orm import Session
from sqlalchemy import text
from src.core.sql_validator import validate_sql
from typing import Tuple


MAX_ROWS = 1000


def execute_query(sql: str, db: Session) -> Tuple[pd.DataFrame, str]:
    is_safe, error = validate_sql(sql)
    if not is_safe:
        return pd.DataFrame(), error

    if not sql.strip().upper().endswith(("LIMIT", "OFFSET")) \
            and "LIMIT" not in sql.upper():
        if "LIMIT" not in sql.upper():
            sql = f"{sql} LIMIT {MAX_ROWS}"

    try:
        result = db.execute(text(sql))
        rows = result.fetchall()
        columns = result.keys()

        df = pd.DataFrame(rows, columns=columns)

        return df, ""

    except Exception as e:
        return pd.DataFrame(), f"SQL execution error: {str(e)}"


def dataframe_to_records(df: pd.DataFrame) -> list[dict]:
    return df.to_dict(orient="records")


def suggest_chart_type(df: pd.DataFrame) -> str | None:
    if df.empty or len(df.columns) < 2:
        return None

    numeric_cols = df.select_dtypes(include=['number']).columns.tolist()
    non_numeric_cols = df.select_dtypes(exclude=['number']).columns.tolist()

    if not numeric_cols or not non_numeric_cols:
        return None

    if len(df) <= 10 and len(df.columns) == 2:
        return "pie"

    if len(df) > 20:
        return "line"

    if len(df.columns) == 2:
        return "bar"

    if len(df.columns) >= 3 and len(numeric_cols) >= 2:
        return "scatter"

    return "bar"