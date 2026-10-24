# Code Review — Conversational BI / NL-to-SQL Assistant

> **Senior Engineer Review** · Depth: deep · Date: 2026-10-22

---

## Overall Rating: 8.2 / 10 ⭐

This is a well-structured, security-conscious project for its domain. The separation of concerns is clean, the defense-in-depth on SQL safety is deliberate and documented, and the test suite covers the critical attack surface. The gaps are real but contained — mostly around schema caching, input validation, concurrency, and missing production-readiness scaffolding.

---

## Summary by Dimension

| Dimension | Score | Notes |
|-----------|-------|-------|
| Architecture & Design | 9/10 | Clear layering, documented invariants, good module ownership |
| Security | 8.5/10 | Strong SQL guardrails; a few gaps remain |
| Code Quality | 8/10 | Readable, well-commented; some minor rough edges |
| Testing | 8.5/10 | Good coverage of the attack surface; eval harness is solid |
| Performance & Scalability | 6/10 | Biggest weakness — schema is re-fetched on every request |
| Error Handling | 8/10 | Good sanitization; a few bare `except Exception` clauses |
| Dependency Hygiene | 7.5/10 | Pinned versions (good); `langchain-community` Ollama import is deprecated |
| Observability | 5/10 | One logger, no structured logging, no tracing, no metrics |
| Docs | 9/10 | ARCHITECTURE.md is excellent; README and invariants are clear |

---

## 🔴 Critical Findings

### C-01 · Schema re-fetched on every `/query` request
**File:** [`src/api/routes.py`](file:///c:/Projects/Conversational%20BI%20%20NL-to-SQL%20Assistant/src/api/routes.py#L50-L52)

```python
# Inside query_endpoint — runs on EVERY request:
schema = inspect_schema(engine)
schema_desc = format_schema_for_prompt(schema)
```

`inspect_schema` hits the information_schema on every single `/query` call. On a busy deployment this is an unnecessary round-trip for every user question and will silently hurt latency. The schema is also passed to `inspect_schema(engine)` by importing `engine` from `session` inside the function body — bypassing FastAPI's dependency injection for the engine, making it harder to swap out in tests.

**Fix:** Cache the schema at startup or use a short TTL (e.g., 60 s with `asyncio.Lock`). Alternatively, compute it once in a `lifespan` event and store in app state.

---

### C-02 · `question` field has no length or content validation
**File:** [`src/api/schemas.py`](file:///c:/Projects/Conversational%20BI%20%20NL-to-SQL%20Assistant/src/api/schemas.py#L5-L7), [`src/api/routes.py`](file:///c:/Projects/Conversational%20BI%20%20NL-to-SQL%20Assistant/src/api/routes.py#L44-L59)

```python
class QueryRequest(BaseModel):
    question: str          # no max_length, no min_length, no strip
    explain: bool = False
```

An adversary (or a runaway client) can send a 1 MB `question` string. That string goes directly into the LLM prompt, incurring token cost and potentially exceeding the context window. It could also be used to attempt prompt injection.

**Fix:**
```python
from pydantic import Field

class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000, strip_whitespace=True)
    explain: bool = False
```

---

## 🟡 Warning Findings

### W-01 · `NLToSQL` global singleton is not thread-safe under concurrent first calls
**File:** [`src/api/routes.py`](file:///c:/Projects/Conversational%20BI%20%20NL-to-SQL%20Assistant/src/api/routes.py#L13-L20)

```python
_nl_to_sql_engine = None

def get_nl_to_sql() -> NLToSQL:
    global _nl_to_sql_engine
    if _nl_to_sql_engine is None:   # ← classic TOCTOU race
        _nl_to_sql_engine = NLToSQL()
    return _nl_to_sql_engine
```

Under concurrent startup requests two workers can race through the `None` check and both instantiate `NLToSQL`, potentially making two API key calls during initialization. The correct fix is to initialize at app startup time.

**Fix:** Use FastAPI's `lifespan` context manager to initialize `NLToSQL` once:
```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.nl_engine = NLToSQL()
    yield

app = FastAPI(lifespan=lifespan)
```

---

### W-02 · `langchain_community.llms.Ollama` is deprecated
**File:** [`src/core/nl_to_sql.py`](file:///c:/Projects/Conversational%20BI%20%20NL-to-SQL%20Assistant/src/core/nl_to_sql.py#L2)

```python
from langchain_community.llms import Ollama
```

`langchain-community` has moved Ollama to the dedicated `langchain-ollama` package. This import will emit deprecation warnings in LangChain 0.3+ and will break in a future version.

**Fix:** Replace with:
```python
from langchain_ollama import OllamaLLM
```
And add `langchain-ollama` to `requirements.txt`.

---

### W-03 · `evaluate_all` is synchronous and blocks indefinitely
**File:** [`src/evaluation/evaluator.py`](file:///c:/Projects/Conversational%20BI%20%20NL-to-SQL%20Assistant/src/evaluation/evaluator.py#L124-L128)

```python
def evaluate_all(self) -> dict:
    items = self.load_questions()
    self.results = [self.evaluate_question(item) for item in items]  # sequential
    return self.compute_metrics()
```

All eval questions run sequentially — one slow LLM call blocks the next. With 20+ eval questions at 1–3 s per call this can take minutes. No timeout per item, no progress indication.

**Fix:** Use `concurrent.futures.ThreadPoolExecutor` with a reasonable worker count (matches LLM rate limits), and add a per-item timeout.

---

### W-04 · `FOR UPDATE` block relies on `BLOCKED_KEYWORDS` but `UPDATE` as a keyword may not fire
**File:** [`src/core/sql_validator.py`](file:///c:/Projects/Conversational%20BI%20%20NL-to-SQL%20Assistant/src/core/sql_validator.py#L41-L52)

```python
# keyword_tokens only checks ttype in T.Keyword
```

`FOR UPDATE` in `SELECT * FROM customers FOR UPDATE` — the unit test `test_blocks_for_update` passes, but the mechanism that blocks it is `UPDATE` appearing as a `T.Keyword` token. This is an implicit and fragile coupling: the test verifies the outcome but not *why* it works. If sqlparse tokenizes `FOR UPDATE` differently on a future version, the block would silently disappear.

**Fix:** Add explicit detection of the `FOR UPDATE` / `FOR SHARE` locking clause, or add `UPDATE` to `BLOCKED_KEYWORDS` with a comment explaining this dual purpose.

---

### W-05 · `call_schema_api` swallows all exceptions silently
**File:** [`src/frontend/utils.py`](file:///c:/Projects/Conversational%20BI%20%20NL-to-SQL%20Assistant/src/frontend/utils.py#L58-L64)

```python
def call_schema_api() -> dict:
    try:
        ...
    except Exception:
        return {}   # ← user sees an empty schema with no explanation
```

A network error, auth failure, or HTTP 500 returns `{}`. The sidebar silently shows nothing — the user has no idea whether schema loading failed or the database is simply empty.

**Fix:** Return a typed result or surface the error in the UI:
```python
except Exception as e:
    st.error(f"Could not load schema: {e}")
    return {}
```

---

### W-06 · Statement timeout only set at connection level, not per-session
**File:** [`src/db/session.py`](file:///c:/Projects/Conversational%20BI%20%20NL-to-SQL%20Assistant/src/db/session.py#L14-L16)

```python
return {"options": f"-c statement_timeout={statement_timeout_ms}"}
```

Setting `statement_timeout` via `connect_args` applies it at connection open time. With connection pooling (`pool_pre_ping=True`), connections are reused. If a connection's timeout has been changed mid-session by another operation, or if a future addition resets the GUC, this protection may not hold. The safer approach is to issue `SET LOCAL statement_timeout` inside each transaction.

---

## 🔵 Info / Quality Findings

### I-01 · `generate_sql` builds the few-shot block outside `build_prompt` — mixed concerns
**File:** [`src/core/nl_to_sql.py`](file:///c:/Projects/Conversational%20BI%20%20NL-to-SQL%20Assistant/src/core/nl_to_sql.py#L34-L43)

```python
few_shot = "\n".join(...)
prompt = build_prompt(question, schema_description)
few_shot_block = f"\n\nExamples:\n{few_shot}\n\nQuestion: {question}\nSQL:"
full_prompt = prompt + few_shot_block
```

The few-shot assembly is in `nl_to_sql.py` but `FEW_SHOT_EXAMPLES` lives in `prompts.py`. Prompt construction is split across two files. `SCHEMA_AWARE_PROMPT` already ends with `SQL Query:` and then the few-shot block appends another `Question: {question}\nSQL:` — the question appears twice in the final prompt.

**Fix:** Move all prompt composition into `prompts.py`. Remove the duplicate question from the appended block or restructure the template.

---

### I-02 · `_nl_to_sql_engine` is module-level state imported at the route level
**File:** [`src/api/routes.py`](file:///c:/Projects/Conversational%20BI%20%20NL-to-SQL%20Assistant/src/api/routes.py#L13)

A module-level global makes testing with `dependency_overrides` non-trivial between tests — if one test initializes the global, subsequent tests inherit it. The existing tests work around this by overriding `get_nl_to_sql`, but the underlying global persists. Moving to `app.state` eliminates this class of test isolation issue.

---

### I-03 · `suggest_chart_type` uses `> 20` rows for line regardless of column semantics
**File:** [`src/core/query_executor.py`](file:///c:/Projects/Conversational%20BI%20%20NL-to-SQL%20Assistant/src/core/query_executor.py#L73)

```python
if len(df) > 20:
    return "line"
```

A result with 25 rows of product names and prices will be rendered as a line chart, which is semantically wrong (line implies a continuous series). This is a product/UX issue more than a bug, but it's worth flagging.

---

### I-04 · No rate limiting on the API
**File:** [`src/api/routes.py`](file:///c:/Projects/Conversational%20BI%20%20NL-to-SQL%20Assistant/src/api/routes.py)

The API key is a single shared secret. There is no per-key rate limiting. A leaked key can be used to hammer the Groq API until quota is exhausted. Consider adding `slowapi` or a middleware-level rate limiter for production deployments.

---

### I-05 · `dataframe_to_records` returns raw Python types — no NaN/Inf sanitization
**File:** [`src/core/query_executor.py`](file:///c:/Projects/Conversational%20BI%20%20NL-to-SQL%20Assistant/src/core/query_executor.py#L46-L47)

```python
def dataframe_to_records(df: pd.DataFrame) -> list[dict]:
    return df.to_dict(orient="records")
```

`pandas` `NaN` / `Inf` values are not JSON-serializable. Pydantic/FastAPI will raise a `ValueError` at serialization time if a query result contains `NULL` numeric cells or infinity. The safe pattern is:
```python
import math
df = df.where(pd.notnull(df), None)
```

---

### I-06 · `conftest.py` sets `GROQ_API_KEY` but not `DATABASE_URL`
**File:** [`tests/conftest.py`](file:///c:/Projects/Conversational%20BI%20%20NL-to-SQL%20Assistant/tests/conftest.py)

Tests rely on the `.env` file being present, or environment variables being set, for `DATABASE_URL` and `API_KEY`. If run in a clean CI environment without a `.env` file, `Settings()` will raise a `ValidationError` before the first test runs. The conftest should set minimal env vars for all required fields.

---

### I-07 · Missing `__all__` exports and no `py.typed` marker
Minor packaging issue — `src` modules don't declare public API surfaces or PEP 561 type stubs. Not blocking for an internal tool, but worth noting if this becomes a library.

---

### I-08 · No observability — logging is minimal, no tracing
There's one `logger = logging.getLogger(__name__)` in `query_executor.py`. No request IDs, no structured JSON logs, no latency metrics, no OpenTelemetry traces. For a BI tool where "why was that query slow?" is a daily question, this is a real operational gap.

---

## Positive Highlights (What's Done Well)

| What | Why it matters |
|------|----------------|
| **Double-validation** (`generate_sql` + `execute_query`) | Defense in depth — the executor cannot be bypassed even by non-LLM callers |
| **Subselect row cap** (`bounded_query`) | Correctly handles trailing comment injection that a simple `LIMIT` append would miss |
| **`secrets.compare_digest` for API key** | Constant-time comparison prevents timing attacks |
| **Driver error sanitization** | `EXECUTION_ERROR` constant prevents SQL/table leakage in error responses |
| **Statement timeout at connect args** | Prevents runaway queries from blocking workers indefinitely |
| **Validator correctly skips string literal tokens** | `WHERE status = 'DELETE'` does not trigger the block — a common false-positive trap |
| **`BLOCKED_IN_COMMENTS` regex** | Explicitly scans comment tokens — correct and unusual for this class of validator |
| **ARCHITECTURE.md invariants section** | Five clearly documented, non-obvious invariants — excellent for team onboarding |
| **`build_explain_prompt` separated from `build_prompt`** | Keeps the SQL-generation prompt free of explanation-mode pollution |
| **Evaluation harness** | `eval_questions.json` + `reference_answers.py` + tolerance-based correctness is production-quality eval design |

---

## Prioritized Fix List

| Priority | Finding | Effort |
|----------|---------|--------|
| 🔴 High | C-01 Schema re-fetched every request | Medium (lifespan + cache) |
| 🔴 High | C-02 No question length/content validation | Low (Field constraints) |
| 🟡 Med | W-01 NLToSQL singleton race condition | Low (move to lifespan) |
| 🟡 Med | W-02 Deprecated Ollama import | Low (swap package) |
| 🟡 Med | W-05 Schema load silently swallows errors | Low (surface to UI) |
| 🟡 Med | I-05 NaN/Inf not sanitized before JSON | Low (df.where) |
| 🟡 Med | I-06 CI env vars not set in conftest | Low |
| 🔵 Low | W-03 Sequential eval blocking | Medium (threadpool) |
| 🔵 Low | W-04 FOR UPDATE block is implicit | Low (add explicit check) |
| 🔵 Low | I-01 Duplicate question in prompt | Low (refactor prompts) |
| 🔵 Low | I-04 No rate limiting | Medium (add slowapi) |
| 🔵 Low | I-08 No structured logging/tracing | High (new infrastructure) |
