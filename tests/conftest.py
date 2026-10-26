import os
import pytest

# Ensure src.config can be imported in test runs without any shell env setup.
# Real deployments set these via .env; tests use an in-memory SQLite database,
# a throwaway API key, and never call a live LLM (LLM construction is mocked or
# overridden).
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "")  # empty = memory buckets default; set to redis://URL for shared buckets
os.environ.setdefault("EXPLAIN_COST_LIMIT", "10000000")
os.environ.setdefault("GROQ_API_KEY", "test-placeholder")
os.environ.setdefault("API_KEY", "test-key")


# Import the production dependency so we can override it in tests
from src.api.routes import get_nl_to_sql  # noqa: F401


@pytest.fixture(autouse=True)
def override_nl_to_sql_engine():
    """Each test gets a fresh NLToSQL engine instance via dependency_overrides.

    This eliminates the module-level _nl_to_sql_engine global as a test
    isolation risk: subsequent tests no longer inherit the first test's
    engine.  The fixture creates a fresh NLToSQL(llm=None) engine (memory‑only,
    no LLM call) and registers it with the FastAPI app so that
    get_nl_to_sql() returns a per‑test engine.

    Yields control to the test, then cleans up the override so the next
    test starts with a fresh state.
    """
    from src.main import app
    from src.core.nl_to_sql import NLToSQL

    # Create a fresh engine for this test (no LLM = memory-safe)
    test_engine = NLToSQL(llm=None)
    app.dependency_overrides[get_nl_to_sql] = lambda: test_engine

    yield

    # Clean up after the test so the next test starts fresh
    if get_nl_to_sql in app.dependency_overrides:
        del app.dependency_overrides[get_nl_to_sql]