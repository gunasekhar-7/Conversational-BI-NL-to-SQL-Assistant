"""Real-Postgres integration tier (env-gated).

Runs only when TEST_DATABASE_URL is set; skips visibly otherwise. These
tests prove the guardrails the SQLite suite cannot: statement_timeout kills
a slow query, the row cap holds, and the schema inspector reads a real
information_schema (REVIEW.md cap 2).
"""

import os
import time

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from src.config import settings
from src.core.query_executor import EXECUTION_ERROR, execute_query
from src.db.schema_inspector import inspect_schema
from src.db.session import build_connect_args

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL not set"),
]


@pytest.fixture(scope="module")
def pg_engine():
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args=build_connect_args(TEST_DATABASE_URL, settings.statement_timeout_ms),
    )
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS seed_rows"))
        conn.execute(text("CREATE TABLE seed_rows (id serial PRIMARY KEY, n integer)"))
        conn.execute(
            text("INSERT INTO seed_rows (n) SELECT g FROM generate_series(1, 1200) AS g")
        )
    yield engine
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS seed_rows"))
    engine.dispose()


@pytest.fixture
def pg_session(pg_engine):
    session = sessionmaker(bind=pg_engine)()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def test_statement_timeout_kills_slow_query(pg_session, monkeypatch):
    monkeypatch.setattr(settings, "statement_timeout_ms", 200)

    start = time.monotonic()
    df, error = execute_query("SELECT pg_sleep(10)", pg_session)
    elapsed = time.monotonic() - start

    assert error == EXECUTION_ERROR
    assert elapsed < 5, f"query should be killed near 200ms, not run 10s (took {elapsed:.1f}s)"


def test_row_cap_returns_exactly_1000_rows(pg_session):
    df, error = execute_query("SELECT * FROM seed_rows", pg_session)

    assert error == ""
    assert len(df) == 1000


def test_explain_guard_rejects_over_limit_on_postgres(pg_session, monkeypatch):
    monkeypatch.setattr(settings, "explain_cost_limit", 0.5)   # any real plan costs more
    df, error = execute_query("SELECT * FROM seed_rows", pg_session)
    assert df.empty and "cost" in error.lower()


def test_inspector_reads_real_catalog(pg_engine):
    schema = inspect_schema(pg_engine)

    assert "seed_rows" in schema
    assert any(c["name"] == "id" for c in schema["seed_rows"]["columns"])
    assert schema["seed_rows"]["primary_key"] == ["id"]
