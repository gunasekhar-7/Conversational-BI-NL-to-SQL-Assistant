from unittest.mock import MagicMock
import pytest
from src.core.nl_to_sql import NLToSQL


def test_generate_sql_with_mock_llm():
    mock_response = MagicMock()
    mock_response.content = "SELECT DISTINCT city FROM customers ORDER BY city"

    mock_llm = MagicMock()
    mock_llm.invoke.return_value = mock_response

    engine = NLToSQL(llm=mock_llm)
    schema = "Table: customers (id, name, email, city)\n"

    sql = engine.generate_sql("list unique cities", schema)

    assert "SELECT" in sql.upper()
    assert "customers" in sql
    mock_llm.invoke.assert_called_once()


def test_cleans_markdown_fences():
    mock_response = MagicMock()
    mock_response.content = "```sql\nSELECT 1\n```"

    mock_llm = MagicMock()
    mock_llm.invoke.return_value = mock_response

    engine = NLToSQL(llm=mock_llm)
    sql = engine.generate_sql("test", "schema")

    assert sql == "SELECT 1"


def test_strips_sql_prefix():
    mock_response = MagicMock()
    mock_response.content = "SQL: SELECT 1"

    mock_llm = MagicMock()
    mock_llm.invoke.return_value = mock_response

    engine = NLToSQL(llm=mock_llm)
    sql = engine.generate_sql("test", "schema")

    assert sql == "SELECT 1"


def test_rejects_unsafe_llm_output():
    mock_response = MagicMock()
    mock_response.content = "DROP TABLE customers"

    mock_llm = MagicMock()
    mock_llm.invoke.return_value = mock_response

    engine = NLToSQL(llm=mock_llm)

    with pytest.raises(ValueError, match="unsafe"):
        engine.generate_sql("test", "schema")


def test_final_prompt_has_question_once_with_examples():
    """Composition belongs to prompts.py; generate_sql must not re-append
    the question (REVIEW.md I-01)."""
    question = "Which carrier shipped fastest in March?"
    mock_response = MagicMock()
    mock_response.content = "SELECT 1"
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = mock_response

    engine = NLToSQL(llm=mock_llm)
    engine.generate_sql(question, "Table: orders (id, carrier_id, delivered_at)")

    prompt_sent = mock_llm.invoke.call_args[0][0][1].content
    assert prompt_sent.count(question) == 1
    assert "Examples:" in prompt_sent


def test_removes_trailing_semicolon():
    mock_response = MagicMock()
    mock_response.content = "SELECT 1;"

    mock_llm = MagicMock()
    mock_llm.invoke.return_value = mock_response

    engine = NLToSQL(llm=mock_llm)
    sql = engine.generate_sql("test", "schema")

    assert sql == "SELECT 1"