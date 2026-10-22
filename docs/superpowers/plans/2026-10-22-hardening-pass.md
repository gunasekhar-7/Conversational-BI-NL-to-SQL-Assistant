# Hardening Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the SQL safety layer correct instead of merely restrictive, close the four exploitable gaps from the security review, and stop the README from claiming things the code does not do.

**Architecture:** The validator becomes token-aware — it reads sqlparse keyword tokens and ignores string literals, so data that merely *contains* the word "DELETE" is allowed while the clause that would actually delete is not. The executor stops appending `LIMIT` (comment-swallowable) and instead wraps the query in a bounded subselect. Authentication becomes a single FastAPI dependency applied at the router, and the Postgres engine gains a statement timeout.

**Tech Stack:** Python 3.11, FastAPI 0.115, SQLAlchemy 2.0, sqlparse 0.5.1, pandera-free pandas, Streamlit 1.65, pytest 8.3.

**Spec:** [docs/superpowers/plans/2026-10-22-hardening-pass.md](2026-10-22-hardening-pass.md) (this plan; it is derived from the audit report in the preceding conversation — no separate spec doc exists).

## Global Constraints

- Validator signature stays `validate_sql(sql: str) -> Tuple[bool, str]`; a rejected query returns `(False, <reason>)`, an accepted one `(True, "")`.
- `execute_query(sql: str, db: Session) -> Tuple[pd.DataFrame, str]` keeps its signature; `error == ""` means success.
- `MAX_ROWS = 1000` remains the cap.
- Only `SELECT` and `WITH` statements are executable; `INSERT/UPDATE/DELETE/DROP/ALTER/TRUNCATE/CREATE/REPLACE/GRANT/REVOKE/EXEC/EXECUTE/MERGE/CALL` and `SELECT … INTO` are rejected.
- String literals are data and must never trigger keyword rejection. Comments containing blocked keywords are still rejected.
- No new runtime dependencies. Tests must pass with no shell environment exported (`tests/conftest.py` supplies defaults).
- Error text returned to API clients must not contain the executed SQL, driver class names, or doc URLs.

## Review Focus

- A legitimate filter value equal to a blocked keyword (`WHERE action = 'DELETE'`) must execute, not be refused.
- A query ending in a line comment must still be capped at 1000 rows.
- A `SELECT … INTO` must be refused even though it starts with `SELECT`.
- `SELECT … FOR UPDATE` and `WITH x AS (DELETE … RETURNING *) SELECT * FROM x` must remain refused.
- A caller without credentials must receive 401 on `/api/query` and `/api/schema`, while `/api/health` stays public for liveness probes.

---

### Task 1: Token-aware SQL validation

**Files:**
- Modify: `src/core/sql_validator.py` (full rewrite)
- Test: `tests/unit/test_sql_validator.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `validate_sql(sql: str) -> Tuple[bool, str]`; `BLOCKED_KEYWORDS: set[str]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_sql_validator.py`:

```python
def test_allows_blocked_keyword_inside_string_literal():
    sql = "SELECT * FROM activity_log WHERE action = 'DELETE'"
    assert validate_sql(sql) == (True, "")

def test_allows_multiple_keywords_inside_literals():
    sql = "SELECT name FROM customers WHERE note = 'please update or create'"
    assert validate_sql(sql) == (True, "")

def test_blocks_select_into():
    is_safe, error = validate_sql("SELECT * INTO evil_copy FROM customers")
    assert not is_safe
    assert "INTO" in error

def test_blocks_delete_returning_cte():
    sql = "WITH d AS (DELETE FROM customers RETURNING *) SELECT * FROM d"
    assert not validate_sql(sql)[0]
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/unit/test_sql_validator.py -q`
Expected: 2 failures on the literal cases, 1 on `SELECT INTO`, 1 on the deleting CTE (`WITH` currently passes only the keyword scan — DELETE is caught, so this one may already pass; confirm).

- [ ] **Step 3: Rewrite `src/core/sql_validator.py`**

Walk `stmt.flatten()`; classify each token by `str(ttype)`. Keyword-ish tokens (`Token.Keyword*`) are the only ones that can reject. `Token.Comment*` tokens are scanned for blocked keywords as well. `Token.Literal.String*`, `Token.Name*`, `Token.Number*`, `Token.Wildcard`, `Token.Operator`, `Token.Punctuation` are skipped. Reject when the first keyword is not `SELECT`/`WITH`, when any keyword is in `BLOCKED_KEYWORDS`, or when a `SELECT`/`WITH` statement contains the keyword `INTO`. Multiple statements (more than one non-empty statement in `sqlparse.parse`) are rejected. Trailing semicolons are tolerated.

- [ ] **Step 4: Run the validator suite**

Run: `python -m pytest tests/unit/test_sql_validator.py -q`
Expected: all pass, including the pre-existing `test_blocks_comment_injection` and `test_allows_cte`.

- [ ] **Step 5: Commit**

```bash
git add src/core/sql_validator.py tests/unit/test_sql_validator.py
git commit -m "fix: validate SQL by token instead of substring so literals stop tripping the filter"
```

---

### Task 2: Structural row cap and non-leaking errors

**Files:**
- Modify: `src/core/query_executor.py`
- Test: `tests/unit/test_query_executor.py`

**Interfaces:**
- Consumes: `validate_sql` from Task 1.
- Produces: `bounded_query(sql: str, limit: int = MAX_ROWS) -> str` (importable helper), unchanged `execute_query`.

- [ ] **Step 1: Write the failing tests**

```python
def test_bounded_query_caps_trailing_comment():
    sql = "SELECT * FROM big -- keep"
    assert bounded_query(sql).endswith("LIMIT 1000")
    assert "-- keep" not in bounded_query(sql).split(") AS _capped")[0].rsplit("\n", 1)[-1]

def test_execution_error_does_not_leak_sql():
    mock_db = MagicMock()
    mock_db.execute.side_effect = Exception('relation "secret_table" does not exist')
    df, error = execute_query("SELECT * FROM secret_table", mock_db)
    assert df.empty
    assert "secret_table" not in error
    assert "SELECT" not in error
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest tests/unit/test_query_executor.py -q`
Expected: `ImportError: cannot import name 'bounded_query'` and a failure on the leak assertion.

- [ ] **Step 3: Implement**

`bounded_query` returns `f"SELECT * FROM (\n{sql}\n) AS _capped LIMIT {limit}"`. `execute_query` validates, executes the bounded form, and on exception logs with `logging.getLogger(__name__).exception(...)` and returns `(pd.DataFrame(), "Query execution failed.")`.

- [ ] **Step 4: Update the pre-existing error test**

`test_execution_error_returns_empty` previously asserted `"SQL execution error" in error`; change it to assert the message is non-empty and does not contain the driver text.

- [ ] **Step 5: Run**

Run: `python -m pytest tests/unit/test_query_executor.py -q` → all pass.

- [ ] **Step 6: Commit**

```bash
git add src/core/query_executor.py tests/unit/test_query_executor.py
git commit -m "fix: bound queries by wrapping rather than appending, and stop echoing driver errors"
```

---

### Task 3: Statement timeout

**Files:**
- Modify: `src/config.py`, `src/db/session.py`
- Test: `tests/unit/test_config.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `Settings.statement_timeout_ms: int` (default `15000`); `build_connect_args(database_url: str, statement_timeout_ms: int) -> dict`.

- [ ] **Step 1: Write the failing test**

```python
def test_statement_timeout_only_for_postgres():
    assert build_connect_args("postgresql://u:p@h/db", 15000) == {
        "options": "-c statement_timeout=15000"
    }
    assert build_connect_args("sqlite://", 15000) == {}
```

- [ ] **Step 2: Run to verify it fails** — `ImportError`.

- [ ] **Step 3: Implement** `build_connect_args` in `src/db/session.py`, pass it to `create_engine(..., connect_args=...)`, and add `statement_timeout_ms: int = 15000` to `Settings`.

- [ ] **Step 4: Run** `python -m pytest tests/unit/test_config.py -q` → pass.

- [ ] **Step 5: Commit**

```bash
git add src/config.py src/db/session.py tests/unit/test_config.py
git commit -m "feat: cap query runtime with a Postgres statement timeout"
```

---

### Task 4: API key authentication

**Files:**
- Create: `src/api/auth.py`
- Modify: `src/config.py` (`api_key: str`), `src/api/routes.py` (router dependency), `.env.example`
- Test: `tests/integration/test_api.py`, `tests/conftest.py`

**Interfaces:**
- Consumes: `settings.api_key`.
- Produces: `require_api_key(x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> None`; raises `HTTPException(401)`.

- [ ] **Step 1: Write the failing tests**

```python
def test_query_requires_api_key(client):
    response = client.post("/api/query", json={"question": "q"})
    assert response.status_code == 401

def test_schema_requires_api_key(client):
    assert client.get("/api/schema").status_code == 401

def test_health_stays_public(client, real_db_override):
    app.dependency_overrides[get_db] = real_db_override
    assert client.get("/api/health").status_code == 200
```

Existing happy-path tests get `headers={"X-API-Key": "test-key"}`; `conftest.py` sets `API_KEY` via `os.environ.setdefault`.

- [ ] **Step 2: Run to verify they fail** — 401 expected but 200/500 returned.

- [ ] **Step 3: Implement** — attach `dependencies=[Depends(require_api_key)]` to the router path operations for `/query` and `/schema` only (health must stay anonymous). Compare with `secrets.compare_digest`. Raise `HTTPException(401, "Invalid or missing API key")`.

- [ ] **Step 4: Run** the integration suite → pass.

- [ ] **Step 5: Commit**

```bash
git add src/api/auth.py src/api/routes.py src/config.py .env.example tests/
git commit -m "feat: require an API key for query and schema access"
```

---

### Task 5: Frontend sends the key and stops dead-ending

**Files:**
- Modify: `src/frontend/utils.py`, `src/frontend/app.py`

**Interfaces:**
- Consumes: the API contract from Task 4.
- Produces: `call_query_api(question: str) -> dict`, `call_schema_api() -> dict` (unchanged signatures).

- [ ] **Step 1:** `utils.py` reads `API_BASE` and `API_KEY` from environment (with the current localhost/`""` defaults) and sends `X-API-Key`.
- [ ] **Step 2:** `app.py` renders a first-run state when `st.session_state.messages` is empty: one line of guidance plus three example-question buttons that populate the prompt. Sidebar gains a "Clear conversation" button.
- [ ] **Step 3:** Error copy in `utils.py` names the remedy ("is the API running on :8000, and is API_KEY set?").
- [ ] **Step 4: Verify live** — start `streamlit run src/frontend/app.py --server.headless true`, open it in the browser tool, confirm the empty state and the API-down error copy render, then stop the server.
- [ ] **Step 5: Commit**

```bash
git add src/frontend/
git commit -m "feat: first-run guidance and actionable errors in the Streamlit UI"
```

---

### Task 6: Make the README true

**Files:**
- Modify: `README.md`

- [ ] **Step 1:** Replace the fake `pytest` transcript and `50 passed in 2.34s` with the real command and the real count from this pass.
- [ ] **Step 2:** Delete the `88.0%` evaluation block; replace with "run `python run_eval.py` to produce `eval_report.json`" and a note that evaluations require a live database and LLM key.
- [ ] **Step 3:** Remove the `See Dockerfile` sentence and the `~1.2s` latency / `85%+ coverage` bullets; keep the inline Dockerfile snippet only if labeled as a starting point.
- [ ] **Step 4:** Add `API_KEY` to the Quick Start and the security section; state the validator is token-based.
- [ ] **Step 5: Verify** — `grep -n "88.0%\|50 passed\|Dockerfile\|85%+\|1.2s" README.md` returns nothing.
- [ ] **Step 6: Commit**

```bash
git add README.md
git commit -m "docs: replace unverifiable claims with the numbers the repo can reproduce"
```
