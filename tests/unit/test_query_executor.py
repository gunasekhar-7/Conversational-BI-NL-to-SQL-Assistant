import pytest
import pandas as pd
from unittest.mock import MagicMock, Mock
from src.core.query_executor import execute_query, suggest_chart_type


def test_blocks_unsafe_sql():
    mock_db = MagicMock()
    df, error = execute_query("DROP TABLE customers", mock_db)
    assert df.empty
    assert "error" in error.lower()
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
    assert "SQL execution error" in error


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


def test_suggest_chart_pie_when_small():
    df = pd.DataFrame({
        'category': ['A', 'B', 'C'],
        'amount': [10, 20, 30]
    })
    assert suggest_chart_type(df) == 'pie'


def test_suggest_chart_none_when_empty():
    df = pd.DataFrame()
    assert suggest_chart_type(df) is None