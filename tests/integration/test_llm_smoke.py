"""End-to-end smoke: a genuine LLM call must produce SQL that validates and runs.

    RUN_LLM_SMOKE=1 GROQ_API_KEY=gsk-... pytest -m llm -v

Never runs in the default suite (costs money, needs a real key): double-gated
by the `llm` marker and the RUN_LLM_SMOKE skipif.
"""
import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.core.nl_to_sql import NLToSQL
from src.core.query_executor import execute_query
from src.core.sql_validator import validate_sql

pytestmark = [
    pytest.mark.llm,
    pytest.mark.skipif(not os.getenv("RUN_LLM_SMOKE"), reason="RUN_LLM_SMOKE not set"),
]

SCHEMA_DESC = (
    "Table: customers\n"
    "  - id: INTEGER (PK)\n"
    "  - name: TEXT\n"
    "  - city: TEXT\n"
)


@pytest.fixture
def customers_session():
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT, city TEXT)"))
        conn.execute(text(
            "INSERT INTO customers (id, name, city) VALUES "
            "(1, 'Ada', 'NYC'), (2, 'Grace', 'LA'), (3, 'Alan', 'NYC')"
        ))
    yield sessionmaker(bind=engine)()


def test_real_llm_generates_valid_sql_that_executes(customers_session):
    engine = NLToSQL()                      # constructs against the real env key
    sql = engine.generate_sql("How many customers are there?", SCHEMA_DESC)

    ok, reason = validate_sql(sql)
    assert ok, f"LLM output failed validation: {reason}"

    df, error = execute_query(sql, customers_session)
    assert error == ""
    assert len(df) == 1                     # a COUNT-style answer: one row
