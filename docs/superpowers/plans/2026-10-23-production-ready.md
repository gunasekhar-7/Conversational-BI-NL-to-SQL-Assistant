# Production-Ready (9+) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. (Native execution recommended: the 11 tasks modify shared files — routes.py, config.py, requirements.txt — so one implementer with fresh reviewer gates at task boundaries avoids interface drift.)

**Goal:** Close the four rating caps and three leftover findings from REVIEW.md so the project earns a 9+ senior-review rating as a production-ready internal tool.

**Architecture:** Keep the existing layering (API → core → db) and add four thin verticals: a Redis-shared rate-limit bucket with multi-key auth, a Prometheus metrics endpoint fed by the request middleware, a dialect-gated `SET LOCAL` timeout inside `execute_query`, and an env-gated real-Postgres test suite. Deployment scaffolding (multi-stage Dockerfile, compose stack, GitHub Actions) wraps the same app without changing how it runs.

**Tech Stack:** FastAPI 0.115.4, SQLAlchemy 2.0.36, slowapi 0.1.10, prometheus-client (new), redis (new), ruff (new, lint-only), pytest 8.3.3, Docker + GitHub Actions.

**Spec:** REVIEW.md — findings W-06, I-03, I-07, plus the four caps from the 8.7 re-rate: (1) one shared key with one 30/min team-wide bucket, (2) all DB tests run SQLite so `statement_timeout`/`FOR UPDATE`/introspection are never proven against real Postgres, (3) per-process schema cache and rate buckets silently degrade under `uvicorn --workers N`, (4) no metrics — p95 latency and failure rates are unanswerable.

**Save location:** `docs/superpowers/plans/2026-10-23-production-ready.md` (write this file as the first step of execution).

## Global Constraints

- Python 3.11+; every dependency pinned to an exact version in `requirements.txt`; `pip check` clean after every install step.
- Default test run must stay fully offline and env-free: only `tests/conftest.py`'s three `setdefault` vars (`DATABASE_URL=sqlite:///:memory:`, `GROQ_API_KEY`, `API_KEY`), no live LLM, no live database. Postgres/Redis tests skip unless their env var is set.
- Preserve the five ARCHITECTURE.md invariants: LLM output and executor input stay double-validated; row cap stays an outer subselect; error messages stay `EXECUTION_ERROR`; API key comparison stays `secrets.compare_digest`.
- All new env vars are optional with working defaults: `DATABASE_URL`, `API_KEY`, `GROQ_API_KEY` remain the only required settings (existing `tests/unit/test_config.py` contract).
- No secrets, API keys, question text, or SQL text may appear in logs, metrics labels, or rate-limit bucket IDs (keys stay SHA-256-hashed).
- Every task ends with: `pytest -q` green (92 + new tests), `ruff check .` green (from Task 1 on), then a commit.
- Rate-limit defaults unchanged: `/query` at `30/minute`; `/api/health` and `/api/metrics` never throttled.

## Review Focus

Failure modes the spec implies that are most likely to bite a user; each line's test lives in the named task.

1. **Metrics label cardinality** — a client requesting 10,000 random nonexistent paths must not create 10,000 label series; unmatched requests collapse to one route-template/`unmatched` label. → test in Task 6.
2. **Redis unreachable** — with `REDIS_URL` set but Redis down, the API must still serve requests (limiter falls back to in-memory) rather than 500ing every call. → test in Task 5.
3. **Forged keys minting buckets** — an attacker cycling random `X-API-Key` values must not get a per-key bucket each (unbounded memory); unknown keys bucket by IP. → test in Task 4.
4. **Dialect safety** — `SET LOCAL` must never execute on SQLite (syntax error would break every default test and sqlite deployments); bare-`MagicMock` sessions in existing tests must be unaffected. → test in Task 2.
5. **Silently-skipped Postgres suite in CI** — the Postgres job must fail if zero Postgres tests ran (pytest exit code 5 on no-selection) instead of passing green while skipping. → gate in Task 11.

---

### Task 1: Ruff lint gate

**Files:**
- Create: `ruff.toml`
- Modify: `requirements.txt`
- Modify: existing files only if `ruff check` reports violations

**Interfaces:**
- Consumes: nothing
- Produces: `ruff check .` as a project-wide gate; every later task includes it in its verification step.

- [ ] **Step 1: Add ruff and pin it**

```bash
pip install ruff
# pin the resolved version in requirements.txt, e.g. ruff==0.12.x — exact value from `pip show ruff`
pip check
```

- [ ] **Step 2: Create `ruff.toml` (lint-only, no formatter, no mass reformat)**

```toml
target-version = "py311"
line-length = 100
[lint]
select = ["E4", "E7", "E9", "F"]   # default pyflakes set: real defects only, no style churn
```

- [ ] **Step 3: Run `ruff check .` and fix any reported violations at their root cause** (unused imports, undefined names). No `# noqa` unless a line is provably correct and unavoidable.

- [ ] **Step 4: Verify**

Run: `ruff check . && pytest -q`
Expected: `All checks passed!` and full suite passes (92 tests at plan start).

- [ ] **Step 5: Commit**

```bash
git add ruff.toml requirements.txt <any fixed files>
git commit -m "chore: add ruff lint gate with default defect-finding rules"
```

---

### Task 2: W-06 — Per-transaction `SET LOCAL statement_timeout`

**Files:**
- Modify: `src/core/query_executor.py` (`execute_query`, ~line 33)
- Test: `tests/unit/test_query_executor.py`

**Interfaces:**
- Consumes: `src.config.settings.statement_timeout_ms` (int, default 15000); existing `execute_query(sql: str, db: Session) -> Tuple[pd.DataFrame, str]` signature unchanged.
- Produces: same public signature; on PostgreSQL dialect only, `execute_query` issues `SET LOCAL statement_timeout = {ms}` as the first statement of the session's transaction, before `bounded_query` runs. `src/db/session.py` `connect_args` stays as the connection-open backstop (do not remove).

- [ ] **Step 1: Write the failing tests**

```python
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
    mock_db = MagicMock()          # bare MagicMock: dialect.name is not "postgresql"
    mock_db.execute.return_value = Mock(**{"fetchall.return_value": [], "keys.return_value": []})

    df, error = execute_query("SELECT 1 AS n", mock_db)

    assert error == ""
    mock_db.execute.assert_called_once()   # exactly one statement, no SET LOCAL
```

(Add `from src.config import settings` to the test file's imports if absent.)

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/unit/test_query_executor.py -k "set_local" -v`
Expected: FAIL — first executed statement is the bounded SELECT, not `SET LOCAL`.

- [ ] **Step 3: Implement in `execute_query`**

Inside the existing `try`, before `db.execute(text(bounded_query(sql)))`: gate on `db.bind.dialect.name == "postgresql"` and execute `text(f"SET LOCAL statement_timeout = {int(settings.statement_timeout_ms)}")` first. SQLAlchemy's Session autobegins the transaction on that first execute, so `SET LOCAL` binds to the same transaction as the query. Comment why: pooled connections may have had their GUC changed mid-session; `SET LOCAL` scopes the cap to this transaction and expires on commit/rollback.

- [ ] **Step 4: Verify**

Run: `pytest tests/unit/test_query_executor.py -v && pytest -q && ruff check .`
Expected: all PASS, including every pre-existing executor test (bare mocks are unaffected by the dialect gate).

- [ ] **Step 5: Commit**

```bash
git add src/core/query_executor.py tests/unit/test_query_executor.py
git commit -m "fix: enforce statement_timeout per transaction via SET LOCAL on Postgres"
```

---

### Task 3: I-03 — Chart suggestion follows column semantics, not row count

**Files:**
- Modify: `src/core/query_executor.py` (`suggest_chart_type`)
- Test: `tests/unit/test_query_executor.py`

**Interfaces:**
- Consumes: pandas DataFrame; existing signature `suggest_chart_type(df: pd.DataFrame) -> str | None`.
- Produces: same signature. New contract: (1) empty frame, <2 columns, or no numeric column → `None`; (2) any datetime column present → `"line"` (continuous time series) regardless of row count; (3) ≥2 numeric columns → `"scatter"`; (4) anything else → `"bar"` — including >20-row categorical results (the old `len(df) > 20 → "line"` rule is removed). Pie remains never auto-suggested.

- [ ] **Step 1: Rewrite/add the failing tests**

`test_suggest_chart_line_when_many_rows` currently pins the wrong contract — replace its body: an int-indexed 25-row frame (`date: range(25), value: range(25)`) must now return `'bar'` (no datetime dtype → categorical). Add:

```python
def test_suggest_chart_line_when_datetime_column():
    df = pd.DataFrame({"day": pd.date_range("2026-01-01", periods=30), "revenue": range(30)})
    assert suggest_chart_type(df) == "line"

def test_categorical_majority_rows_stay_bar():
    df = pd.DataFrame({"city": [f"c{i}" for i in range(25)], "orders": range(25)})
    assert suggest_chart_type(df) == "bar"
```

Keep `test_suggest_chart_bar`, `test_small_categorical_defaults_to_bar`, `test_suggest_chart_scatter_when_multiple_numeric`, `test_suggest_chart_none_when_empty` unchanged — they must still pass.

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/unit/test_query_executor.py -k "chart" -v`
Expected: FAIL on the datetime test and the rewritten 25-row test.

- [ ] **Step 3: Implement**

In `suggest_chart_type`: delete the `if len(df) > 20: return "line"` branch; insert before the numeric-count check: `if len(df.select_dtypes(include=["datetime", "datetimetz"]).columns) > 0: return "line"`. Update the docstring contract to the four rules above.

- [ ] **Step 4: Verify**

Run: `pytest tests/unit/test_query_executor.py -k chart -v && pytest -q && ruff check .`
Expected: all PASS. Also grep the frontend for `"line"` handling to confirm no row-count assumption lives there: `grep -rn '"line"' src/frontend`.

- [ ] **Step 5: Commit**

```bash
git add src/core/query_executor.py tests/unit/test_query_executor.py
git commit -m "fix: suggest line charts only for datetime series, not long categorical results"
```

---

### Task 4: Multiple API keys + configurable rate limit

**Files:**
- Modify: `src/config.py` (Settings)
- Modify: `src/api/auth.py`
- Modify: `src/api/routes.py` (`QUERY_RATE_LIMIT`, `rate_limit_key`)
- Modify: `.env.example`
- Test: `tests/unit/test_auth.py` (create), `tests/unit/test_config.py`, `tests/integration/test_api.py`

**Interfaces:**
- Consumes: existing `settings.api_key` (str, required — unchanged contract).
- Produces:
  - `Settings.api_keys: str = ""` — comma-separated extra keys; `Settings.query_rate_limit: str = "30/minute"`.
  - `src.api.auth.is_valid_api_key(key: str) -> bool` — true if key matches `api_key` or any non-empty entry of `api_keys`, each checked with `secrets.compare_digest`.
  - `require_api_key` keeps its signature and 401 detail, delegating to `is_valid_api_key`.
  - `rate_limit_key(request)` returns `key:<sha256[:32]>` **only when `is_valid_api_key` passes**, else `ip:<address>` (Review Focus #3).
  - Routes decorator: `@limiter.limit(settings.query_rate_limit)` (env-tunable, default identical).

- [ ] **Step 1: Write failing tests**

`tests/unit/test_auth.py`:

```python
def test_accepts_primary_and_extra_keys(monkeypatch):
    monkeypatch.setattr(settings, "api_key", "primary")
    monkeypatch.setattr(settings, "api_keys", "alpha, beta,,")
    assert is_valid_api_key("primary")
    assert is_valid_api_key("alpha")
    assert is_valid_api_key("beta")
    assert not is_valid_api_key("gamma")

def test_unknown_key_buckets_by_ip_not_by_key():
    req = make_request(x_api_key="forged-123")   # build a starlette Request scope with that header + client
    assert rate_limit_key(req).startswith("ip:")

def test_valid_key_buckets_by_hashed_key():
    req = make_request(x_api_key="test-key")     # conftest default
    bucket = rate_limit_key(req)
    assert bucket.startswith("key:") and "test-key" not in bucket
```

`tests/unit/test_config.py`: add `assert settings.query_rate_limit == "30/minute"` and `assert settings.api_keys == ""` defaults. `tests/integration/test_api.py`: add a test that a request with `X-API-Key: alpha` (settings monkeypatched with `api_keys="alpha"`) gets 200 on `/api/query` with the standard mocked overrides.

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/unit/test_auth.py tests/unit/test_config.py -v`
Expected: FAIL — `is_valid_api_key` not importable.

- [ ] **Step 3: Implement**

Config: two new `BaseSettings` fields with defaults above. Auth: implement `is_valid_api_key` comparing against `(settings.api_key, *[k.strip() for k in settings.api_keys.split(",") if k.strip()])` using `compare_digest` per candidate; `require_api_key` becomes a 3-line delegation. Routes: replace the `QUERY_RATE_LIMIT` constant with `settings.query_rate_limit` at the decorator, and gate `rate_limit_key`'s key-branch on `is_valid_api_key`. Update `.env.example` with commented `API_KEYS=` and `QUERY_RATE_LIMIT=30/minute`.

- [ ] **Step 4: Verify**

Run: `pytest -q && ruff check .`
Expected: all PASS — including the pre-existing `test_rate_limit_bucket_is_per_api_key` (it monkeypatches `settings.api_key = "second-key"`, still valid) and `test_query_rejects_wrong_api_key`.

- [ ] **Step 5: Commit**

```bash
git add src/config.py src/api/auth.py src/api/routes.py .env.example tests/unit/test_auth.py tests/unit/test_config.py tests/integration/test_api.py
git commit -m "feat: accept multiple API keys and env-tunable query rate limit"
```

---

### Task 5: Redis-shared rate limiter with in-memory fallback

**Files:**
- Modify: `src/api/routes.py` (limiter construction)
- Modify: `src/config.py` (`redis_url: str | None = None`)
- Modify: `requirements.txt` (add `redis`, pinned)
- Modify: `.env.example`
- Test: `tests/unit/test_limiter_storage.py` (create)

**Interfaces:**
- Consumes: Task 4's `rate_limit_key`; slowapi `Limiter(key_func=..., storage_uri=...)`.
- Produces: `build_storage_uri(redis_url: str | None, ping=None) -> str` in `src/api/routes.py` — returns `redis_url` when given and the ping succeeds, else `"memory://"`; module `limiter = Limiter(key_func=rate_limit_key, storage_uri=build_storage_uri(settings.redis_url))`. The `limiter` name stays module-level (imported by `src/main.py` and tests unchanged).

- [ ] **Step 1: Write failing tests**

```python
def test_defaults_to_memory_when_no_redis_url():
    assert build_storage_uri(None) == "memory://"

def test_uses_redis_when_reachable():
    assert build_storage_uri("redis://localhost:6379/0", ping=lambda url: True) == "redis://localhost:6379/0"

def test_falls_back_to_memory_when_redis_unreachable():   # Review Focus #2
    assert build_storage_uri("redis://localhost:6379/0", ping=lambda url: False) == "memory://"

def test_default_limiter_storage_is_memory_in_tests():
    from src.api.routes import limiter
    assert "MemoryStorage" in type(limiter.limiter.storage).__name__
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/unit/test_limiter_storage.py -v`
Expected: FAIL — `build_storage_uri` undefined.

- [ ] **Step 3: Implement**

`build_storage_uri` takes `ping` (defaults to a lazy `redis.Redis.from_url(url).ping` inside try/except `Exception` → False, so the import stays optional at module scope). Lint the reachable-URL path with a 1s socket timeout so startup never hangs. Construct the module limiter with the result. Add `redis==<pinned>` to `requirements.txt`; `pip check` must pass.

- [ ] **Step 4: Verify**

Run: `pytest -q && ruff check . && pip check`
Expected: all PASS; the 429 integration tests still pass on memory storage.

- [ ] **Step 5: Commit**

```bash
git add src/api/routes.py src/config.py requirements.txt .env.example tests/unit/test_limiter_storage.py
git commit -m "feat: share rate-limit buckets across workers via Redis, fall back to memory"
```

---

### Task 6: Prometheus metrics endpoint

**Files:**
- Create: `src/api/metrics.py`
- Modify: `src/main.py` (middleware records observations)
- Modify: `src/api/routes.py` (`GET /metrics`, unthrottled, unauthenticated)
- Modify: `requirements.txt` (`prometheus-client`, pinned)
- Test: `tests/integration/test_metrics.py` (create)

**Interfaces:**
- Consumes: `request_logging_middleware` already computes `request_id`, status, `duration_ms`; `request.scope["route"].path` gives the route template.
- Produces in `src/api/metrics.py`:
  - `REGISTRY` (a `CollectorRegistry`)
  - `HTTP_REQUESTS = Counter("http_requests_total", "Requests", ["method", "path", "status"], registry=REGISTRY)`
  - `HTTP_LATENCY = Histogram("http_request_duration_seconds", "Request latency", ["method", "path"], registry=REGISTRY)`
  - `SQL_GENERATION_FAILURES = Counter("sql_generation_failures_total", "LLM SQL generation failures", registry=REGISTRY)`
  - `QUERY_FAILURES = Counter("query_execution_failures_total", "Rejected or failed queries", registry=REGISTRY)`
  - `observe_request(method: str, path: str, status: int, duration_seconds: float) -> None`
  - `metrics_response() -> Response` rendering `generate_latest(REGISTRY)` with `CONTENT_TYPE_LATEST`.
  - `path` is always `request.scope.get("route").path` after routing, or `"unmatched"` when no route matched (Review Focus #1).

- [ ] **Step 1: Write failing tests**

```python
def test_metrics_endpoint_exposes_request_series(client):
    client.get("/api/health")
    body = client.get("/api/metrics")
    assert body.status_code == 200
    assert "http_requests_total" in body.text
    assert "http_request_duration_seconds" in body.text

def test_random_404_paths_collapse_to_one_label(client):    # Review Focus #1
    for i in range(50):
        client.get(f"/api/definitely-not-a-route-{i}")
    body = client.get("/api/metrics")
    assert 'path="unmatched"' in body.text
    assert "definitely-not-a-route" not in body.text

def test_metrics_body_contains_no_user_content(client):    # no question/SQL leakage
    # run one /api/query with mocked overrides asking "how many customers?"
    assert "how many customers" not in client.get("/api/metrics").text
    assert "SELECT" not in client.get("/api/metrics").text

def test_metrics_endpoint_never_throttled(client):
    assert all(client.get("/api/metrics").status_code == 200 for _ in range(35))
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/integration/test_metrics.py -v`
Expected: FAIL — 404 on `/api/metrics`.

- [ ] **Step 3: Implement**

Module as specced above. In `request_logging_middleware`, after `duration_ms` is computed, call `observe_request(request.method, route_path_or_unmatched, status, duration_ms / 1000)` on both success and exception paths. Add `@router.get("/metrics")` returning `metrics_response()` — no `require_api_key` dependency, no limiter decorator (same rationale as `/health`: probes must never be blocked). In `query_endpoint`, increment `SQL_GENERATION_FAILURES` in the generation `except` and `QUERY_FAILURES` when `execute_query` returns an error. Add `prometheus-client==<pinned>` to requirements; `pip check`.

- [ ] **Step 4: Verify**

Run: `pytest -q && ruff check .`
Expected: all PASS. Existing logging tests in `tests/integration/test_request_logging.py` unaffected (middleware only gained a call).

- [ ] **Step 5: Commit**

```bash
git add src/api/metrics.py src/main.py src/api/routes.py requirements.txt tests/integration/test_metrics.py
git commit -m "feat: expose Prometheus request latency and failure counters at /api/metrics"
```

---

### Task 7: Health reports LLM readiness

**Files:**
- Modify: `src/api/routes.py` (`health_check`)
- Modify: `src/api/schemas.py` (`HealthResponse`)
- Test: `tests/integration/test_api.py`

**Interfaces:**
- Consumes: `request.app.state.nl_engine` / `nl_engine_error` (set by `lifespan`).
- Produces: `HealthResponse(status: str, database: str, llm: str)` where `llm` is `"ready"` or `"unavailable"`; endpoint signature gains `request: Request`.

- [ ] **Step 1: Write failing tests**

```python
def test_health_reports_llm_ready(client, real_db_override):
    app.dependency_overrides[get_db] = real_db_override
    data = client.get("/api/health").json()
    assert data["llm"] == "ready"

def test_health_reports_llm_unavailable_when_not_initialized(client, real_db_override):
    app.dependency_overrides[get_db] = real_db_override
    client.app.state.nl_engine = None
    data = client.get("/api/health").json()
    assert data["llm"] == "unavailable"
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/integration/test_api.py -k health -v`
Expected: FAIL — `llm` key missing.

- [ ] **Step 3: Implement**

Add `llm: str` to `HealthResponse`; in `health_check`, read `request.app.state.nl_engine` (via `getattr(..., None)`) and return `"ready"`/`"unavailable"`. Orchestrators can now distinguish "DB down" from "LLM key missing" — note in the response docstring.

- [ ] **Step 4: Verify**

Run: `pytest -q && ruff check .` → all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/api/routes.py src/api/schemas.py tests/integration/test_api.py
git commit -m "feat: report LLM readiness on /api/health for orchestrator probes"
```

---

### Task 8: Real-Postgres integration suite (env-gated) + test compose file

**Files:**
- Create: `pytest.ini`
- Create: `docker-compose.test.yml`
- Create: `tests/integration/test_postgres.py`
- Modify: `README.md` (test section: how to run the Postgres tier)

**Interfaces:**
- Consumes: `src.core.query_executor.execute_query`, `src.db.schema_inspector.inspect_schema`, `src.db.session.build_connect_args`, `src.config.settings.statement_timeout_ms`.
- Produces: marker `postgres` (registered in `pytest.ini` with `--strict-markers`); tests run iff `TEST_DATABASE_URL` is set, else skip with a visible reason. `docker-compose.test.yml` exposes Postgres 16 on port 5433, user/pass/db `nlsql_test`, healthcheck `pg_isready`.

- [ ] **Step 1: Write `pytest.ini` and the compose file**

```ini
[pytest]
addopts = --strict-markers
markers =
    postgres: requires a live PostgreSQL (set TEST_DATABASE_URL)
```

`docker-compose.test.yml`: one service `postgres` (`postgres:16-alpine`, env `POSTGRES_USER=nlsql`, `POSTGRES_PASSWORD=nlsql`, `POSTGRES_DB=nlsql_test`, port `5433:5432`, healthcheck `pg_isready -U nlsql`).

- [ ] **Step 2: Write the failing tests (module-level `pytestmark = pytest.mark.postgres` + `skipif` on `TEST_DATABASE_URL`)**

```python
@pytest.fixture(scope="module")
def pg_engine(): ...   # create_engine(TEST_DATABASE_URL, connect_args=build_connect_args(...)); create seed table with 1200 rows; yield; drop

def test_statement_timeout_kills_slow_query(pg_session, monkeypatch):
    monkeypatch.setattr(settings, "statement_timeout_ms", 200)
    df, error = execute_query("SELECT pg_sleep(10)", pg_session)
    assert error == EXECUTION_ERROR      # proven against real Postgres, not mocked

def test_row_cap_returns_exactly_1000_rows(pg_session):
    df, error = execute_query("SELECT * FROM seed_rows", pg_session)
    assert error == "" and len(df) == 1000

def test_inspector_reads_real_catalog(pg_engine):
    schema = inspect_schema(pg_engine)
    assert "seed_rows" in schema
    assert any(c["name"] == "id" for c in schema["seed_rows"]["columns"])
```

- [ ] **Step 3: Run without env — verify skip**

Run: `pytest tests/integration/test_postgres.py -v`
Expected: SKIPPED with `TEST_DATABASE_URL not set` reason; `pytest -q` overall green (skips don't fail).

- [ ] **Step 4: Run against live Postgres — verify pass**

```bash
docker compose -f docker-compose.test.yml up -d --wait
export TEST_DATABASE_URL=postgresql+psycopg2://nlsql:nlsql@localhost:5433/nlsql_test
pytest tests/integration/test_postgres.py -v
docker compose -f docker-compose.test.yml down
```
Expected: 3 passed (task instructions: if no Docker daemon is available on this machine, record that as a limitation and defer the live run to CI in Task 11 — do not claim it passed).

- [ ] **Step 5: Commit**

```bash
git add pytest.ini docker-compose.test.yml tests/integration/test_postgres.py README.md
git commit -m "test: add env-gated real-Postgres suite for timeout, row cap, and catalog"
```

---

### Task 9: I-07 — Packaging hygiene (`__all__` + `py.typed`)

**Files:**
- Create: `src/py.typed`
- Modify: `src/core/sql_validator.py`, `src/core/query_executor.py`, `src/core/nl_to_sql.py`, `src/core/prompts.py`
- Test: `tests/unit/test_public_api.py` (create)

**Interfaces:**
- Produces: `__all__` in each of the four core modules listing their public names (`validate_sql`, `execute_query`, `bounded_query`, `dataframe_to_records`, `suggest_chart_type`, `NLToSQL`, `build_prompt`, `build_explain_prompt`, `FEW_SHOT_EXAMPLES`, `SCHEMA_AWARE_PROMPT`, … — exact list = the names the existing test suite imports from each module); `src/py.typed` empty marker.

- [ ] **Step 1: Write failing test**

```python
@pytest.mark.parametrize("module", [sql_validator, query_executor, nl_to_sql, prompts])
def test_core_modules_declare_public_api(module):
    assert hasattr(module, "__all__") and module.__all__
    for name in module.__all__:
        assert hasattr(module, name)

def test_typed_marker_exists():
    assert Path(src.__file__).parent.joinpath("py.typed").exists()
```

- [ ] **Step 2: Run to verify failure** → `pytest tests/unit/test_public_api.py -v` FAIL.

- [ ] **Step 3: Implement** `__all__` tuples and the empty `src/py.typed` file.

- [ ] **Step 4: Verify** → `pytest -q && ruff check .` all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/py.typed src/core tests/unit/test_public_api.py
git commit -m "chore: declare core module public APIs and add PEP 561 marker"
```

---

### Task 10: Multi-stage Dockerfile + compose stack + README ops

**Files:**
- Create: `Dockerfile`, `.dockerignore`, `docker-compose.yml`
- Modify: `README.md` (replace the skeleton-Dockerfile section with real usage; document all env vars, `uvicorn --workers` guidance, per-process schema-cache staleness ≤ 60s)

**Interfaces:**
- Consumes: `uvicorn src.main:app` (README line 106), settings from env; Tasks 4–7's env vars.
- Produces: image serving API on 8000, non-root user, `HEALTHCHECK` hitting `/api/health`; compose services `api` (build ., port 8000), `postgres` (from `docker-compose.test.yml` pattern, port 5432), `redis` (6379); `.env` values passed via `env_file`/`environment`.

- [ ] **Step 1: Write `Dockerfile` (multi-stage)**

Stage 1 `python:3.11-slim AS builder`: `pip install --prefix=/install -r requirements.txt`. Stage 2 `python:3.11-slim`: `COPY --from=builder /install`, `WORKDIR /app`, `COPY src/ src/`, `RUN useradd --create-home app` + `USER app`, `EXPOSE 8000`, `HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health', timeout=3)"`, `CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]`.

`.dockerignore`: `.git`, `.env`, `tests`, `docs`, `__pycache__`, `*.md`, `.superpowers`, `venv`.

- [ ] **Step 2: Write `docker-compose.yml`** — `api` (build ., `env_file: .env`, depends_on postgres+redis healthy), `postgres` (16-alpine, healthcheck), `redis` (7-alpine, healthcheck), wiring `DATABASE_URL`/`REDIS_URL` to service hostnames.

- [ ] **Step 3: Build and smoke-test**

```bash
docker build -t nl-to-sql:test .
docker compose -f docker-compose.yml config -q   # validates the file
```
Expected: build succeeds; config validates. (If no Docker daemon on this machine, record as limitation — CI in Task 11 builds the image.)

- [ ] **Step 4: Update README ops section** (real commands, full env-var table: required vs optional, worker guidance, metrics endpoint note).

- [ ] **Step 5: Commit**

```bash
git add Dockerfile .dockerignore docker-compose.yml README.md
git commit -m "feat: add multi-stage container image and compose stack for the API"
```

---

### Task 11: GitHub Actions CI (lint + tests + Postgres tier + image build)

**Files:**
- Create: `.github/workflows/ci.yml`
- Modify: `README.md` (badge optional — skip unless remote exists)

**Interfaces:**
- Consumes: Task 1's `ruff check .`; Task 8's `postgres` marker and `TEST_DATABASE_URL`; Task 10's Dockerfile.

- [ ] **Step 1: Write the workflow**

Four jobs on push/PR: **lint** (`ruff check .`); **test** (`pip install -r requirements.txt && pytest tests/unit tests/integration --ignore=tests/integration/test_postgres.py -q`); **postgres** (service `postgres:16-alpine` with health-cmd, `TEST_DATABASE_URL` env, `pytest -m postgres` — pytest exits 5 when zero tests match, failing the job if the suite silently skips (Review Focus #5); the `skipif` won't trigger because the env var is set); **docker** (`docker build .`).

- [ ] **Step 2: Validate locally as far as possible**

Run: `python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/ci.yml'))"` (or `ruff check . && pytest -q` as the local proxy) plus the exact four commands the jobs run, skipping jobs whose infra (Docker daemon) is absent — record what could not run.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: lint, test, postgres-tier, and image-build jobs"
```

---

### Task 12: Final verification pass + docs sync

**Files:**
- Modify: `README.md`, `docs/ARCHITECTURE.md` (ops/metrics/limiter notes only)

- [ ] **Step 1: Run the full local matrix**

```bash
ruff check . && pytest -q && pip check
```
Expected: lint clean, all tests pass with only conftest's three env vars and no `.env` (verify env is scrubbed: `env | grep -E "GROQ|API_KEY|DATABASE_URL"` shows nothing exported), `pip check` reports no broken requirements.

- [ ] **Step 2: Re-score against REVIEW.md**

Update the README/ARCHITECTURE ops notes (metrics endpoint, multi-key auth, Redis fallback semantics, Postgres tier, schema-cache per-process staleness ≤ 60s) and state the re-rated dimensions with the evidence for each cap closed.

- [ ] **Step 3: Commit**

```bash
git add README.md docs/ARCHITECTURE.md
git commit -m "docs: record production-readiness evidence and re-score"
```
