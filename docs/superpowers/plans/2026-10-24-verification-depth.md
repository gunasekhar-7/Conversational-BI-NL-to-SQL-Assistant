# Verification Depth + EXPLAIN Cost Guard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. (Native execution: the 5 tasks touch shared files — pytest.ini, ci.yml, README — sequentially, so one implementer avoids edit collisions. All README prose edits are consolidated into Task 5.)

**Goal:** Close three of the five caps from the 9.1 senior rating (live-Redis shared buckets, zero frontend tests, no real-LLM run) and add the one selected feature — a Postgres EXPLAIN cost guard that moves safety from syntactic validation to actual query-plan cost.

**Architecture:** No product restructuring. One new defense layer inside `execute_query` (dialect-gated exactly like the existing `SET LOCAL`), one env-gated test file per external system (Redis, LLM), an in-process Streamlit `AppTest` suite for the page, and CI jobs that run each tier. Every new test skips cleanly in the default offline suite.

**Tech Stack:** pytest 8.3.3, streamlit 1.40.1 (`streamlit.testing.v1.AppTest` — ships with streamlit), stdlib `json` for plan parsing, slowapi + redis (already pinned), GitHub Actions. **Zero new runtime dependencies.**

**Spec:** The 9.1 rating's five caps — this plan closes #1 (Redis sharing proven only by injection), #4 (frontend blind spot), #5 (no real-LLM run). Cap #2 (CI never executed) gets its missing jobs here but needs a push to finish; cap #3 (fresh-eyes review) is a process step outside this plan. Feature scope is the EXPLAIN guard only — audit log, conversation memory, and result cache were offered and declined; async conversion, SSE streaming, pagination, and embedding-based schema selection were considered and excluded as non-goals at this scale.

**Save location:** `docs/superpowers/plans/2026-10-24-verification-depth.md` (write this file as the first step of execution).

## Global Constraints

- **Zero new runtime dependencies** — AppTest ships with the pinned streamlit; plan parsing uses stdlib json. `pip check` remains clean except its pre-existing, out-of-scope opencv/shap numpy complaints.
- Default test run stays fully offline/env-free: only conftest's three `setdefault` vars. Redis/LLM/Postgres tests skip unless `TEST_REDIS_URL` / `RUN_LLM_SMOKE` / `TEST_DATABASE_URL` are set.
- Preserve the five ARCHITECTURE.md invariants. Double-validation, the outer-subselect row cap, and `EXECUTION_ERROR` for driver errors are untouched. **New, explicitly allowed:** the cost-guard rejection is a distinct user-facing message containing only the estimated cost and the configured limit — no table names, no SQL (the SQL already ships in `QueryResponse.sql`).
- `EXECUTION_ERROR` stays for driver failures; the cost message is its own string.
- EXPLAIN guard defaults generous: `explain_cost_limit: float = 10_000_000.0`, Postgres-only, `<= 0` disables. Rationale pinned: cartesian-product runaway plans estimate at 1e9+ while ordinary scans/joins on an internal dataset stay far below 1e7 — the guard catches runaways and never rejects legitimate work.
- Every task ends with: `pytest -q` green, `ruff check .` green, then a commit.
- Expected offline counts after all tasks: **123 passed, 7 skipped** (4 Postgres + 2 Redis + 1 LLM) — always confirm against actual output, never assert from arithmetic.
- Windows/Git Bash command syntax.

## Review Focus

Failure modes the spec implies that no task's happy-path test exercises; each line's test lives in the named task.

1. **SQLite/default path must not regress** — the EXPLAIN pass is Postgres-only; a bare-mock or SQLite session still sees exactly one statement per query. → tests in Task 3.
2. **Guard malfunction must fail open** — unparseable EXPLAIN output logs a warning and executes the query anyway (availability first; the statement timeout remains the safety backstop). → test in Task 3.
3. **No false-green Redis wiring** — with `TEST_REDIS_URL` set, storage that comes back memory-backed must FAIL loudly; the subprocess design makes this independent of import order, so no run context can false-fail or false-pass it. → test in Task 1.
4. **Frontend tests must never hit the network** — every test that triggers `call_query_api`/`call_schema_api` patches them first; wrong patch paths raise `AttributeError` at patch time, failing loudly rather than silently passing. → tests in Task 2.
5. **LLM smoke must never run or spend in the default suite** — double-gated (`llm` marker + `RUN_LLM_SMOKE` skipif); default runs show it skipped. → test in Task 4.

---

### Task 1: Live Redis shared-bucket proof

**Files:**
- Modify: `docker-compose.test.yml` (add redis service on host port **6380**)
- Modify: `pytest.ini` (register `redis` marker)
- Create: `tests/integration/test_redis_rate_limit.py`
- Modify: `.github/workflows/ci.yml` (new `redis` job)

**Interfaces:**
- Consumes: `src.api.routes.limiter` (module-limiter built at import from `settings.redis_url`), slowapi `Limiter(key_func=..., storage_uri=...)`, `limits.storage.RedisStorage`.
- Produces: marker `redis`; `TEST_REDIS_URL` convention (e.g. `redis://127.0.0.1:6380/0` locally, `redis://127.0.0.1:6379/0` in CI).

- [ ] **Step 1: Extend `docker-compose.test.yml` and register the marker**

Add (updating the file's header comment with the run command):

```yaml
  redis:
    image: redis:7-alpine
    ports:
      - "6380:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 3s
      timeout: 3s
      retries: 20
```

Validate: `docker compose -f docker-compose.test.yml config -q` → exit 0.

`pytest.ini` markers block gains: `redis: requires a live Redis (set TEST_REDIS_URL)`.

- [ ] **Step 2: Write the failing tests**

```python
# tests/integration/test_redis_rate_limit.py
"""Shared-bucket proof (REVIEW.md cap 3 / 9.1 rating cap 1).

    docker compose -f docker-compose.test.yml up -d redis --wait
    TEST_REDIS_URL=redis://127.0.0.1:6380/0 pytest -m redis -v
    docker compose -f docker-compose.test.yml down

Safe in any run context: both tests consume TEST_REDIS_URL directly and the
wiring check runs in a fresh subprocess, so earlier imports in this process
cannot poison the result.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

TEST_REDIS_URL = os.getenv("TEST_REDIS_URL")
pytestmark = [
    pytest.mark.redis,
    pytest.mark.skipif(not TEST_REDIS_URL, reason="TEST_REDIS_URL not set"),
]

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_wiring_builds_redis_storage_when_configured():
    """Fresh interpreter: app wiring must construct RedisStorage when REDIS_URL is set.

    Review Focus: if the ping fails and storage silently falls back to memory,
    this FAILS with MemoryStorage in stderr — it never skips and never passes
    green on the wrong storage.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from src.api.routes import limiter; "
            "from limits.storage import RedisStorage; "
            "assert isinstance(limiter.limiter.storage, RedisStorage), "
            "f'got {type(limiter.limiter.storage).__name__}'",
        ],
        env={**os.environ, "REDIS_URL": TEST_REDIS_URL},
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"stdout={result.stdout} stderr={result.stderr}"


def test_buckets_shared_across_two_limiter_instances():
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded

    def make_app():
        app = FastAPI()
        lim = Limiter(key_func=lambda request: "shared-key", storage_uri=TEST_REDIS_URL)
        app.state.limiter = lim
        app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

        @app.get("/ping")
        @lim.limit("2/minute")
        def ping(request: Request):
            return {"ok": True}

        return app, lim

    app_a, lim_a = make_app()
    app_b, _ = make_app()
    try:
        a = TestClient(app_a)
        assert [a.get("/ping").status_code for _ in range(2)] == [200, 200]
        assert a.get("/ping").status_code == 429

        # Separate app, separate Limiter instance — only shared Redis can
        # explain a 429 on the very first request of instance B.
        b = TestClient(app_b)
        assert b.get("/ping").status_code == 429, "bucket must be shared through Redis"
    finally:
        lim_a.limiter.storage.reset()
```

- [ ] **Step 3: Verify the skip path**

Run: `pytest tests/integration/test_redis_rate_limit.py -v` (no env) → Expected: 2 SKIPPED (`TEST_REDIS_URL not set`). Then `pytest -q` → green.

- [ ] **Step 4: Run live against Redis**

```bash
docker compose -f docker-compose.test.yml up -d redis --wait
TEST_REDIS_URL=redis://127.0.0.1:6380/0 pytest -m redis -v
docker compose -f docker-compose.test.yml down
```
Expected: 2 passed. (If no Docker daemon: record as limitation and defer to CI — do not claim passed.)

- [ ] **Step 5: Add the CI `redis` job**

```yaml
  redis:
    runs-on: ubuntu-latest
    services:
      redis:
        image: redis:7-alpine
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 3s
          --health-timeout 3s
          --health-retries 20
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
      - run: pip install -r requirements.txt
      - run: pytest tests/integration/test_redis_rate_limit.py -v
        env:
          TEST_REDIS_URL: redis://127.0.0.1:6379/0
```

(Standalone invocation = exit-5 gate: zero collected tests fails the job.)

- [ ] **Step 6: Verify + commit**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml')); print('ok')"` and `pytest -q && ruff check .` → `ok`, green, clean.

```bash
git add docker-compose.test.yml pytest.ini tests/integration/test_redis_rate_limit.py .github/workflows/ci.yml
git commit -m "test: prove rate-limit buckets are shared across limiter instances via Redis"
```

---

### Task 2: Streamlit AppTest suite (characterization tests)

**Files:**
- Create: `tests/integration/test_frontend_app.py`

**Interfaces:**
- Consumes: `src/frontend/app.py` (script-level page: `st.session_state.messages` list of dicts `{role, content, sql?, data?, chart_type?, explanation?}`; `st.chat_input` submit; example buttons rendered only when messages are empty; sidebar button "🔄 Load Schema"); `src.frontend.utils.call_query_api(question, explain=...) -> dict` and `call_schema_api() -> (schema, error)` — patched at the module, re-bound on each script run.
- Produces: 4 page-level tests in the default suite; no new dependency, no network.

- [ ] **Step 1: Write the tests**

```python
# tests/integration/test_frontend_app.py
"""Page-level characterization tests driving the real Streamlit script in-process.

These pin shipped behavior — green on first run is the expected outcome;
Step 2 proves each test has teeth via a mutation probe.
"""
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

APP = "src/frontend/app.py"

OK_RESPONSE = {
    "sql": "SELECT COUNT(*) AS n FROM customers",
    "results": [{"n": 3}],
    "columns": ["n"],
    "row_count": 1,
    "error": None,
    "chart_suggestion": None,
    "explanation": None,
}

EXAMPLES = {
    "How many customers do we have?",
    "Show total revenue by city",
    "What are the top 5 products by price?",
}


def test_empty_state_renders_examples_and_chat_input():
    at = AppTest.from_file(APP).run()

    assert not at.exception
    assert "Conversational BI" in at.title[0].value
    # Subset, not equality: the sidebar contributes its own buttons to the tree.
    assert EXAMPLES <= {b.label for b in at.button}
    assert at.chat_input[0].label == "Ask a question about your data..."


def test_successful_query_renders_answer_and_message_history():
    at = AppTest.from_file(APP)
    with patch("src.frontend.utils.call_query_api", return_value=OK_RESPONSE):
        at.chat_input[0].set_value("How many customers?")
        at.run()

    assert not at.exception
    messages = at.session_state["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert "Found **1** rows" in messages[1]["content"]
    assert messages[1]["sql"] == OK_RESPONSE["sql"]
    assert messages[1]["data"].equals(pd.DataFrame([{"n": 3}]))


def test_error_response_surfaces_in_conversation():
    at = AppTest.from_file(APP)
    with patch(
        "src.frontend.utils.call_query_api",
        return_value={"error": "Query execution failed. See the server log for details.",
                      "sql": "SELECT 1"},
    ):
        at.chat_input[0].set_value("bad question")
        at.run()

    assert not at.exception
    assistant = at.session_state["messages"][1]
    assert assistant["content"].startswith("❌")
    assert "See the server log" in assistant["content"]


def test_load_schema_failure_shows_sidebar_error():
    at = AppTest.from_file(APP)
    with patch(
        "src.frontend.utils.call_schema_api",
        return_value=({}, "Could not reach the API at http://localhost:8000 — is uvicorn running?"),
    ):
        load_button = next(b for b in at.sidebar.button if b.label == "🔄 Load Schema")
        load_button.click()
        at.run()

    assert not at.exception
    assert at.error, "schema failure must surface via st.error"
    assert "uvicorn" in at.error[0].value
```

- [ ] **Step 2: Run + mutation probe (the RED gate for characterization tests)**

Run: `pytest tests/integration/test_frontend_app.py -v` → Expected: 4 passed (shipped behavior).

Then prove teeth — two quick mutations, each watched failing, then restored:
1. Change `OK_RESPONSE["row_count"]` to `99` locally → `test_successful_query...` must FAIL on the `Found **1** rows` assertion. Restore.
2. Change the success-test patch target to `"src.frontend.app.call_query_api"` → the patch must ERROR (`AttributeError` — proves patch paths are real module attributes, not no-ops). Restore.

Record both observed failures in the ledger before committing.

- [ ] **Step 3: Verify**

Run: `pytest -q && ruff check .` → Expected: 119 passed, 5 skipped, clean lint.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_frontend_app.py
git commit -m "test: drive the Streamlit page in-process with AppTest"
```

---

### Task 3: EXPLAIN cost guard (Postgres)

**Files:**
- Modify: `src/core/query_executor.py` (`execute_query` + new `_plan_cost`)
- Modify: `src/config.py` (`explain_cost_limit: float = 10_000_000.0`)
- Modify: `.env.example`
- Modify: `tests/integration/test_postgres.py` (live rejection test)
- Test: `tests/unit/test_query_executor.py`

**Interfaces:**
- Consumes: the existing dialect gate (`db.bind.dialect.name == "postgresql"`), `settings` read at call time (monkeypatchable), `bounded_query(sql)` output as the statement to EXPLAIN (the actual executed statement).
- Produces: `_plan_cost(db: Session, bounded_sql: str) -> float | None` — executes `EXPLAIN (FORMAT JSON) <bounded>`, takes row[0] (accepts str or pre-parsed list: psycopg2 auto-parses json columns), reads `[0]["Plan"]["Total Cost"]`, returns `float`; returns `None` on **any** failure (fail-open, `logger.warning(..., exc_info=True)`). `execute_query` signature/return contract unchanged; when `cost > settings.explain_cost_limit` it returns the rejection tuple **before executing the query** with message: `f"Query plan cost {cost:,.0f} exceeds the limit ({settings.explain_cost_limit:,.0f}). Simplify the question or raise EXPLAIN_COST_LIMIT."`

**Known existing-test impact (explicit):** `test_sets_local_timeout_on_postgres_before_query` pins call indices `[0]=SET LOCAL, [1]=_capped`; the EXPLAIN call becomes `[1]` and the query `[2]` — Step 1 rewrites those three assertions.

- [ ] **Step 1: Write/update the failing tests**

Update `test_sets_local_timeout_on_postgres_before_query`:

```python
    stmts = [str(c.args[0]) for c in mock_db.execute.call_args_list]
    assert stmts[0].startswith("SET LOCAL statement_timeout")
    assert str(settings.statement_timeout_ms) in stmts[0]
    assert stmts[1].startswith("EXPLAIN (FORMAT JSON)")
    assert "_capped" in stmts[2]   # bare MagicMock fetchone -> unparseable -> fail-open -> query runs
```

Add:

```python
def _pg_mock(responses):
    """Postgres-mock whose execute() answers by statement prefix."""
    from types import SimpleNamespace

    mock_db = MagicMock()
    mock_db.bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

    def execute(stmt):
        text = str(stmt)
        if text.startswith("SET LOCAL"):
            return Mock()
        if text.startswith("EXPLAIN"):
            return responses["explain"]
        return responses["query"]

    mock_db.execute.side_effect = execute
    return mock_db


def _query_ok():
    r = Mock()
    r.fetchall.return_value = [(1,)]
    r.keys.return_value = ["n"]
    return r


def test_explain_rejects_plan_over_cost_limit():
    from src.config import settings as cfg
    assert cfg.explain_cost_limit == 10_000_000.0   # default pinned here

    explain = Mock()
    explain.fetchone.return_value = ([{"Plan": {"Total Cost": 900_000_000.0}}],)  # cartesian-bomb scale
    mock_db = _pg_mock({"explain": explain, "query": _query_ok()})

    df, error = execute_query("SELECT id FROM customers", mock_db)

    assert df.empty
    assert "cost" in error.lower() and "exceeds" in error.lower()
    assert mock_db.execute.call_count == 2   # SET LOCAL + EXPLAIN only; query never ran


def test_explain_allows_plan_within_cost_limit(monkeypatch):
    monkeypatch.setattr("src.core.query_executor.settings.explain_cost_limit", 100.0)
    explain = Mock()
    explain.fetchone.return_value = ([{"Plan": {"Total Cost": 12.5}}],)
    mock_db = _pg_mock({"explain": explain, "query": _query_ok()})

    df, error = execute_query("SELECT id FROM customers", mock_db)

    assert error == ""
    assert mock_db.execute.call_count == 3


def test_explain_guard_disabled_when_limit_nonpositive(monkeypatch):
    monkeypatch.setattr("src.core.query_executor.settings.explain_cost_limit", 0)
    mock_db = _pg_mock({"explain": Mock(), "query": _query_ok()})

    df, error = execute_query("SELECT id FROM customers", mock_db)

    assert error == ""
    assert mock_db.execute.call_count == 2      # SET LOCAL + query; EXPLAIN never issued


def test_explain_malformed_output_fails_open():
    explain = Mock()
    explain.fetchone.return_value = ("<not json at all>",)   # str path -> json.loads raises
    mock_db = _pg_mock({"explain": explain, "query": _query_ok()})

    df, error = execute_query("SELECT id FROM customers", mock_db)

    assert error == ""                            # guard malfunction must not block queries
    assert mock_db.execute.call_count == 3
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/unit/test_query_executor.py -v` → Expected: the updated index test fails (no EXPLAIN at `[1]`), all four new tests fail (wrong call counts / no cost error).

- [ ] **Step 3: Implement**

`src/core/query_executor.py`: add `import json`; add `_plan_cost(db, bounded_sql) -> float | None` exactly as specced (fail-open with `logger.warning`). In `execute_query`, inside the existing Postgres branch after `SET LOCAL`, when `settings.explain_cost_limit > 0`: compute `bounded = bounded_query(sql)` once (reuse for EXPLAIN and execution), reject with the message tuple if over — all before the query executes. `src/config.py`: `explain_cost_limit: float = 10_000_000.0` with a comment pinning the rationale (catches 1e9+ runaway estimates, never fires on ordinary internal queries; `<= 0` disables; Postgres-only). `.env.example`: `# EXPLAIN_COST_LIMIT=10000000`.

- [ ] **Step 4: Live Postgres test**

Add to `tests/integration/test_postgres.py`:

```python
def test_explain_guard_rejects_over_limit_on_postgres(pg_session, monkeypatch):
    monkeypatch.setattr(settings, "explain_cost_limit", 0.5)   # any real plan costs more
    df, error = execute_query("SELECT * FROM seed_rows", pg_session)
    assert df.empty and "cost" in error.lower()
```

Run: `pytest -q && ruff check .` → Expected: 123 passed, 6 skipped, clean lint.

- [ ] **Step 5: Live tier**

```bash
docker compose -f docker-compose.test.yml up -d --wait
TEST_DATABASE_URL=postgresql+psycopg2://nlsql:nlsql@localhost:5433/nlsql_test pytest -m postgres -v
docker compose -f docker-compose.test.yml down
```
Expected: 4 passed — the 3 pre-existing must stay green: they prove EXPLAIN executes on real Postgres and the default 10M threshold passes real plans.

- [ ] **Step 6: Commit**

```bash
git add src/core/query_executor.py src/config.py .env.example tests/unit/test_query_executor.py tests/integration/test_postgres.py
git commit -m "feat: reject Postgres query plans above a configured EXPLAIN cost limit"
```

---

### Task 4: Real-LLM end-to-end smoke test

**Files:**
- Create: `tests/integration/test_llm_smoke.py`
- Modify: `pytest.ini` (register `llm` marker)
- Modify: `.github/workflows/ci.yml` (`workflow_dispatch` trigger + gated `llm-smoke` job)

**Interfaces:**
- Consumes: `NLToSQL()` against the real env key (real `GROQ_API_KEY` must be in the shell **before** pytest starts — conftest's `setdefault` never overwrites it), `validate_sql`, `execute_query` on a fixture-built SQLite customers table.
- Produces: marker `llm`; gate = `RUN_LLM_SMOKE=1` (never implied by key presence).

- [ ] **Step 1: Register marker + write the test**

`pytest.ini` gains: `llm: real-LLM smoke (set RUN_LLM_SMOKE=1 and provide a real GROQ_API_KEY)`.

```python
# tests/integration/test_llm_smoke.py
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
```

- [ ] **Step 2: Verify the gate**

Run: `pytest tests/integration/test_llm_smoke.py -v` → Expected: 1 SKIPPED (`RUN_LLM_SMOKE not set`). `pytest -q` green.

- [ ] **Step 3: Live run if a real key exists**

Check: `python -c "import os; k=os.getenv('GROQ_API_KEY',''); print('real-key' if k and not k.startswith('test-') else 'no-real-key')"`.
If `real-key`: `RUN_LLM_SMOKE=1 pytest tests/integration/test_llm_smoke.py -v` → Expected: 1 passed.
If `no-real-key`: **record honestly in the ledger that the live LLM run is unverified here** — gate behavior and CI wiring are verified instead; the user runs it with their key.

- [ ] **Step 4: CI wiring**

`ci.yml`: add `workflow_dispatch:` under `on:`; add:

```yaml
  llm-smoke:
    if: github.event_name == 'workflow_dispatch'
    runs-on: ubuntu-latest
    env:
      GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}
      RUN_LLM_SMOKE: "1"
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
      - run: pip install -r requirements.txt
      - run: pytest tests/integration/test_llm_smoke.py -v
        if: env.GROQ_API_KEY != ''
```

(Manual-only: pushes never spend money; absent secret = step skipped, job green.)

Validate: `python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml')); print('ok')"`.

- [ ] **Step 5: Verify + commit**

Run: `pytest -q && ruff check .` → green (smoke skipped).

```bash
git add tests/integration/test_llm_smoke.py pytest.ini .github/workflows/ci.yml
git commit -m "test: add opt-in real-LLM end-to-end smoke with manual CI job"
```

---

### Task 5: Docs sync, safety story, final matrix

**Files:**
- Modify: `README.md` (all prose consolidated here: test tiers + counts from an actual run, `EXPLAIN_COST_LIMIT` env row, Performance & Safety bullet, re-score Testing row evidence)
- Modify: `docs/ARCHITECTURE.md` (Execution module row mentions the plan-cost guard; one sentence under Key invariants item 1: safety is three-layer — validation → plan cost → statement timeout)

- [ ] **Step 1: Full verification matrix**

```bash
export -n DATABASE_URL GROQ_API_KEY API_KEY REDIS_URL TEST_DATABASE_URL RUN_LLM_SMOKE 2>/dev/null
env | grep -E "GROQ|API_KEY|DATABASE_URL|REDIS_URL|LLM_SMOKE" || echo env-clean
ruff check . && pytest -q && pip check 2>&1 | grep -v -E "opencv-python|shap"; echo deps-ok
```
Expected: `env-clean`, lint clean, default-tier tests green with redis/llm/postgres skipped (expect 123 passed, 7 skipped — use actual output), `deps-ok`. Then both live tiers in one compose session:

```bash
docker compose -f docker-compose.test.yml up -d --wait
TEST_DATABASE_URL=postgresql+psycopg2://nlsql:nlsql@localhost:5433/nlsql_test pytest -m postgres -q
TEST_REDIS_URL=redis://127.0.0.1:6380/0 pytest -m redis -q
docker compose -f docker-compose.test.yml down
```
Expected: 4 + 2 passed. Plus `docker compose config -q` for the full stack.

- [ ] **Step 2: Docs sync**

README test section: real counts from Step 1, with three optional tiers and their exact commands (postgres / redis / llm). Env table row: `EXPLAIN_COST_LIMIT` (default 10000000, `<=0` disables, Postgres-only). Performance & Safety bullet: plan-cost guard before execution, statement timeout as backstop. Re-score Testing row: add frontend + Redis + LLM tiers to the evidence. ARCHITECTURE.md: the two edits above.

- [ ] **Step 3: Commit**

```bash
git add README.md docs/ARCHITECTURE.md
git commit -m "docs: sync test tiers, three-layer safety story, and re-score evidence"
```

## Self-Review

1. **Spec coverage:** Redis cap → Task 1; frontend cap → Task 2; LLM cap → Task 4; EXPLAIN feature → Task 3; docs/consistency → Task 5. CI cap gets its missing jobs (Tasks 1/4) but a push is still required to finish it — stated, not hidden; review cap is process, out of scope — stated in Spec. Declared non-goals absent from every task.
2. **Step scan:** each step is one test batch, one run-to-fail (or, for Task 2's characterization tests, an explicit mutation probe with recorded failures), one signature-scoped implementation, one verification, one commit. No step decides nothing; no step transcribes a body the signature and tests already pin.
3. **Type consistency:** `_plan_cost(db, bounded_sql) -> float | None` identical across spec and tests; monkeypatch target `"src.core.query_executor.settings.explain_cost_limit"` matches where settings is imported; `TEST_REDIS_URL`/`RUN_LLM_SMOKE`/`EXPLAIN_COST_LIMIT` spelled identically across tests, compose, CI, and env templates; the one existing-test edit is named exactly (`test_sets_local_timeout_on_postgres_before_query`) with its three rewritten assertions given verbatim.
4. **Review Focus:** all five lines have owning tasks and named tests: T1 (subprocess wiring assert), T2 (patch-at-real-module + network-free seams), T3 (called_once counts for SQLite-style sessions + fail-open malformed test), T4 (double gate), and the default-suite run in T5 confirms every gate simultaneously.
5. **Proportion:** 5 tasks, ~7 product/config files touched + 3 new test files; code blocks exist only for assertions, EXPLAIN JSON shapes, and compose/CI YAML where exactness matters. Revision over v1: Redis test no longer mutates process env or requires standalone runs (subprocess design); characterization gate is concrete (two mutations, recorded); default cost limit raised to 10M with a pinned rationale; README churn consolidated into Task 5.
