# Architecture

## Data flow

```
┌──────────────┐   HTTP + X-API-Key   ┌──────────────────┐
│  Streamlit UI │ ───────────────────▶ │   FastAPI API     │
│  frontend/    │ ◀─────────────────── │   api/routes.py   │
└──────────────┘                      └────────┬─────────┘
                                               │
                     ┌─────────────────────────┼─────────────────────────┐
                     ▼                         ▼                         ▼
            ┌────────────────┐       ┌────────────────┐       ┌────────────────┐
            │  Schema         │       │  NLToSQL       │       │  Executor      │
            │  Inspector      │       │  (LangChain)   │       │  query_executor│
            │  db/schema_     │       │  core/nl_to_   │       │                │
            │  inspector.py   │       │  sql.py        │       │                │
            └────────┬───────┘       └───────┬────────┘       └───────┬────────┘
                     │                       │                        │
                     │ table/column/         │ schema_description     │
                     │ FK metadata           │ + question             │
                     │                       ▼                        │
                     │              ┌────────────────┐                │
                     │              │  Prompt Builder │                │
                     │              │  core/prompts   │                │
                     │              └───────┬────────┘                │
                     │                      │                         │
                     │                      ▼                         │
                     │              ┌────────────────┐                │
                     │              │  Groq / Ollama  │                │
                     │              │  LLM            │                │
                     │              └───────┬────────┘                │
                     │                      │ raw SQL text            │
                     │                      ▼                         │
                     │              ┌────────────────┐                │
                     │              │  SQL Validator  │                │
                     │              │  core/sql_      │                │
                     │              │  validator.py   │                │
                     │              └───────┬────────┘                │
                     │                      │ validated SQL           │
                     │                      ▼                         │
                     └─────────────────────▶│◀────────────────────────┘
                                            ▼
                                   ┌────────────────┐
                                   │  Database       │
                                   │  (PostgreSQL /  │
                                   │   SQLite)       │
                                   └───────┬────────┘
                                           │ rows
                                           ▼
                                   ┌────────────────┐
                                   │  DataFrame      │
                                   │  + chart type   │
                                   └───────┬────────┘
                                           │
                                           ▼
                                   ┌────────────────┐
                                   │  JSON response  │
                                   │  sql, rows,     │
                                   │  chart_suggestion│
                                   └────────────────┘
```

## Module ownership

| Module | File | Owns |
|--------|------|------|
| **Validation** | `src/core/sql_validator.py` | Whether a SQL string is safe to run. Walks sqlparse keyword tokens; rejects DDL/DML, multi-statements, `SELECT ... INTO`, and blocked keywords in comments. Returns `(bool, str)`. |
| **Execution** | `src/core/query_executor.py` | Runs validated SQL against a session. On Postgres, issues `SET LOCAL statement_timeout` first so the cap is scoped to this transaction even on pooled connections. Applies a 1,000-row cap by wrapping in an outer subselect so a trailing comment cannot disable it. Sanitizes driver errors. Suggests a chart type from the result frame (datetime → line, ≥2 numeric → scatter, else bar). |
| **NL engine** | `src/core/nl_to_sql.py` | Builds the LLM prompt, calls the provider, strips markdown fences and prefixes, and re-validates via `validate_sql` before returning. |
| **Prompts** | `src/core/prompts.py` | Prompt template and few-shot examples. No runtime logic. |
| **Schema** | `src/db/schema_inspector.py` | Reads table/column/PK/FK metadata from an engine and formats it for the prompt. |
| **Session** | `src/db/session.py` | Creates the SQLAlchemy engine and session factory. Applies a Postgres statement timeout via connect args. |
| **API** | `src/api/routes.py` | HTTP contract. Depends on `get_db` and `get_nl_to_sql` (both via app.state, built once in the lifespan handler). `/query` (throttled per key via slowapi, limit from `QUERY_RATE_LIMIT`) and `/schema` require an API key; `/health` and `/metrics` do not — probes must never be blocked. Schema introspection is served through a 60s TTL cache. |
| **Auth** | `src/api/auth.py` | `require_api_key` plus `is_valid_api_key`: one primary key and optional comma-separated `API_KEYS`, each compared with `secrets.compare_digest`. Only valid keys get their own rate-limit bucket; forged keys share the caller's IP bucket. |
| **Metrics** | `src/api/metrics.py` | Prometheus registry and instruments: request count/latency, SQL-generation failures, query failures. Labels are route templates or `unmatched` — never raw paths or user text. |
| **Validation schemas** | `src/api/schemas.py` | Pydantic request/response models. |
| **Config** | `src/config.py` | All settings via pydantic-settings; loaded once at import. Required: `DATABASE_URL`, `API_KEY` (+`GROQ_API_KEY` for Groq). Optional: `API_KEYS`, `QUERY_RATE_LIMIT`, `REDIS_URL`, `STATEMENT_TIMEOUT_MS`, LLM provider settings. |
| **Frontend** | `src/frontend/app.py` | Streamlit page: session state, empty-state examples, message history. |
| **Frontend components** | `src/frontend/components.py` | Rendering helpers: chat bubbles, SQL blocks, tables, charts, schema viewer. |
| **Frontend API client** | `src/frontend/utils.py` | HTTP calls to the API; maps HTTP failures to human-readable messages. |
| **Evaluation** | `src/evaluation/evaluator.py` | Loads eval questions, runs each through the full pipeline, and computes accuracy metrics against expected row counts, scalar approximations, and exact string values. |
| **Reports** | `src/evaluation/reports.py` | Pretty-prints metrics and saves JSON reports. |

## Key invariants

1. **Validation happens twice.** Once inside `NLToSQL.generate_sql` (rejects unsafe model output before it leaves the engine) and once inside `execute_query` (rejects anything that arrives there, including SQL from non-LLM callers). This is intentional: the executor is the last line of defense.

2. **The row cap cannot be commented out.** `execute_query` never appends `LIMIT` to the raw SQL. It wraps it: `SELECT * FROM (<sql>) AS _capped LIMIT 1000`. A trailing `--` comment in the original SQL terminates at the newline the wrapper inserts.

3. **Driver errors never reach the caller.** `execute_query` logs the full exception and returns a generic message. The SQL, table names, and dialect internals stay in the server log.

4. **Auth is per-route.** `/health` is anonymous so liveness probes work without a secret. `/query` and `/schema` require `X-API-Key`.

5. **The evaluation is reproducible.** Expected values in `data/eval_questions.json` were measured by running reference SQL (`scripts/reference_answers.py`) against a database built from `data/sample_schema.sql` + `data/sample_data.sql`. They are not hand-written guesses.
