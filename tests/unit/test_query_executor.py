import pandas as pd
from unittest.mock import MagicMock, Mock

from src.config import settings
from src.core.query_executor import (
    EXECUTION_ERROR,
    bounded_query,
    dataframe_to_records,
    execute_query,
    suggest_chart_type,
)


def test_dataframe_to_records_sanitizes_nan_and_inf():
    """NaN/Inf are not valid JSON; strict serializers reject them at send time."""
    import json
    import math

    df = pd.DataFrame(
        {
            "a": [1.0, float("nan"), float("inf")],
            "b": [float("-inf"), None, 2.5],
        }
    )

    records = dataframe_to_records(df)

    # allow_nan=False mirrors what the ASGI JSON layer enforces: a raw
    # Infinity or NaN in the payload is invalid JSON and would 500 the request.
    json.dumps(records, allow_nan=False)

    assert records[0] == {"a": 1.0, "b": None}
    assert records[1]["a"] is None
    assert records[2]["a"] is None
    for row in records:
        for value in row.values():
            if isinstance(value, float):
                assert math.isfinite(value)


def test_blocks_unsafe_sql():
    mock_db = MagicMock()
    df, error = execute_query("DROP TABLE customers", mock_db)
    assert df.empty
    assert "select" in error.lower()
    mock_db.execute.assert_not_called()


def test_valid_select_returns_dataframe():
    mock_result = Mock()
    mock_result.fetchall.return_value = [(1, 'test')]
    mock_result.keys.return_value = ['id', 'name']

    mock_db = MagicMock()
    mock_db.execute.return_value = mock_result

    df, error = execute_query("SELECT id, name FROM customers", mock_db)

    assert error == ""
    assert len(df) == 1
    mock_db.execute.assert_called_once()


def test_sets_local_timeout_on_postgres_before_query():
    mock_db = MagicMock()
    mock_db.bind.dialect.name = "postgresql"
    mock_result = Mock()
    mock_result.fetchall.return_value = [(1,)]
    mock_result.keys.return_value = ["n"]
    mock_db.execute.return_value = mock_result

    df, error = execute_query("SELECT 1 AS n", mock_db)

    assert error == ""
    first_stmt = str(mock_db.execute.call_args_list[0].args[0])
    assert first_stmt.startswith("SET LOCAL statement_timeout")
    assert str(settings.statement_timeout_ms) in first_stmt
    assert "_capped" in str(mock_db.execute.call_args_list[1].args[0])


def test_skips_set_local_on_non_postgres_dialect():
    mock_db = MagicMock()  # bare MagicMock: dialect.name is never the string "postgresql"
    mock_db.execute.return_value = Mock(
        **{"fetchall.return_value": [], "keys.return_value": []}
    )

    df, error = execute_query("SELECT 1 AS n", mock_db)

    assert error == ""
    mock_db.execute.assert_called_once()  # exactly one statement, no SET LOCAL


def test_execution_error_returns_empty():
    mock_db = MagicMock()
    mock_db.execute.side_effect = Exception("relation does not exist")

    df, error = execute_query("SELECT * FROM nonexistent", mock_db)

    assert df.empty
    assert error == EXECUTION_ERROR


def test_execution_error_does_not_leak_sql_or_driver_text():
    mock_db = MagicMock()
    mock_db.execute.side_effect = Exception(
        'relation "secret_table" does not exist [SQL: SELECT * FROM secret_table]'
    )

    df, error = execute_query("SELECT * FROM secret_table", mock_db)

    assert df.empty
    assert "secret_table" not in error
    assert "SELECT" not in error
    assert "relation" not in error


def test_bounded_query_wraps_with_outer_limit():
    bounded = bounded_query("SELECT * FROM big")

    assert bounded.endswith("LIMIT 1000")
    assert "SELECT * FROM big" in bounded


def test_bounded_query_caps_query_with_trailing_comment():
    bounded = bounded_query("SELECT * FROM big -- keep going")

    # The comment ends at the newline the wrapper inserts, leaving the closing
    # parenthesis and the LIMIT outside it.
    assert "-- keep going\n" in bounded
    assert bounded.splitlines()[-1] == ") AS _capped LIMIT 1000"


def test_bounded_query_strips_trailing_semicolon():
    bounded = bounded_query("SELECT 1;")

    assert ";\n) AS _capped" not in bounded
    assert "SELECT 1" in bounded


def test_suggest_chart_bar():
    df = pd.DataFrame({
        'city': ['NYC', 'LA', 'Chicago'],
        'revenue': [100, 200, 150]
    })
    assert suggest_chart_type(df) == 'bar'


def test_suggest_chart_line_when_datetime_column():
    # Small on purpose: a short time series must still read as a line even
    # though it is under any row-count threshold.
    df = pd.DataFrame({
        "day": pd.date_range("2026-01-01", periods=10),
        "revenue": range(10),
    })
    assert suggest_chart_type(df) == "line"


def test_categorical_majority_rows_stay_bar():
    # 25 rows of names+values is categorical, not a series: a line chart
    # would imply continuity the data does not have (REVIEW.md I-03).
    df = pd.DataFrame({
        'city': [f"c{i}" for i in range(25)],
        'orders': list(range(25))
    })
    assert suggest_chart_type(df) == 'bar'


def test_small_categorical_defaults_to_bar():
    # Contract: no automatic pie suggestion — categorical vs numeric
    # defaults to bar regardless of frame size.
    df = pd.DataFrame({
        'category': ['A', 'B', 'C'],
        'amount': [10, 20, 30]
    })
    assert suggest_chart_type(df) == 'bar'


def test_suggest_chart_scatter_when_multiple_numeric():
    df = pd.DataFrame({
        'city': ['NYC', 'LA', 'Chicago'],
        'revenue': [100, 200, 150],
        'orders': [5, 9, 7]
    })
    assert suggest_chart_type(df) == 'scatter'


def test_suggest_chart_none_when_empty():
    df = pd.DataFrame()
    assert suggest_chart_type(df) is None
