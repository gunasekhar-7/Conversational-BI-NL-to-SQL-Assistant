import pandas as pd
from unittest.mock import MagicMock, Mock

from src.core.query_executor import (
    EXECUTION_ERROR,
    bounded_query,
    execute_query,
    suggest_chart_type,
)


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


def test_suggest_chart_line_when_many_rows():
    df = pd.DataFrame({
        'date': list(range(25)),
        'value': list(range(25))
    })
    assert suggest_chart_type(df) == 'line'


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
