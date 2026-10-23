# Conversational BI / NL-to-SQL Assistant

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115.4-009688.svg)](https://fastapi.tiangolo.com/)
[![LangChain](https://img.shields.io/badge/LangChain-0.3.7-00a36d.svg)](https://www.langchain.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791.svg)](https://www.postgresql.org/)

Transform natural language questions into SQL queries with full schema awareness, safety guards, and execution accuracy measurement.

## Features

### 🎯 Natural Language to SQL
- Ask questions in plain English: *"top 5 products by revenue last quarter"*
- Schema-aware prompting with table/column/relationship context
- Few-shot examples for common query patterns
- Groq API + Llama 3.1 70B or local Ollama support

### 🔐 SQL Safety Layer
- **Only SELECT/WITH queries allowed** — DROP, DELETE, UPDATE, INSERT, ALTER, TRUNCATE all blocked
- Multi-statement injection blocked (semicolons, UNION attacks)
- Comment-based injection blocked (`-- DROP TABLE`)
- Full validation before any database execution
- Result set limiting (1000 rows max) prevents runaway queries

### 📊 Interactive Visualizations
- Automatic chart type suggestion (bar, line, scatter)
- Plotly-powered interactive charts
- Streamlit conversational UI with SQL exploration

### 📈 Evaluation Framework
- **50 test questions** across 5 complexity tiers:
  - Simple SELECTs (10)
  - Aggregations with GROUP BY (10)
  - Multi-table JOINs (10)
  - Complex filters and ordering (10)
  - CTEs, subqueries, window functions (10)
- Metrics: SQL generation accuracy, execution success rate, **execution accuracy**
- JSON report export for CI/CD integration

### 🏗️ Architecture
- **FastAPI** backend with SQLAlchemy + PostgreSQL
- **LangChain** orchestration with schema inspector
- **Streamlit** frontend with chat interface
- Modular design: `core/` (NL engine, validator, executor), `db/` (models, session), `api/` (routes), `frontend/` (UI), `evaluation/` (metrics)

## Quick Start

### 1. Prerequisites
```bash
# PostgreSQL running locally
psql --version  # 14+
python --version  # 3.11+
```

### 2. Clone & Setup
```bash
git clone https://github.com/yourusername/nl-to-sql-assistant.git
cd nl-to-sql-assistant

python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

### 3. Configure Environment
```bash
cp .env.example .env
```

Edit `.env`:
```env
DATABASE_URL=postgresql://user:password@localhost:5432/nl_to_sql
API_KEY=change-me-before-deploy  # sent as X-API-Key header by the frontend and callers
GROQ_API_KEY=your_groq_api_key_here
LLM_PROVIDER=groq  # or "ollama"
LLM_MODEL=llama-3.1-70b-versatile
STATEMENT_TIMEOUT_MS=15000       # Postgres: cancel queries that run longer than this
```

**Get Groq API Key:** https://console.groq.com/keys (free tier available)

**Or use Ollama locally:**
```bash
ollama pull llama3.1
# .env: LLM_PROVIDER=ollama, OLLAMA_BASE_URL=http://localhost:11434
```

### 4. Initialize Database
```bash
createdb nl_to_sql
psql nl_to_sql < data/sample_schema.sql
psql nl_to_sql < data/sample_data.sql
```

### 5. Run Tests
```bash
pytest -v
```

Expected: 115 passing, 3 skipped. The suite is fully offline: it uses an
in-memory SQLite database and a mocked LLM (no `.env`, no network needed).

The 3 skipped tests are the real-Postgres tier (`tests/integration/test_postgres.py`),
which proves the SQLite suite cannot: `statement_timeout` killing a slow query,
the 1,000-row cap, and catalog introspection. Run them with:

```bash
docker compose -f docker-compose.test.yml up -d --wait
TEST_DATABASE_URL=postgresql+psycopg2://nlsql:nlsql@localhost:5433/nlsql_test \
  pytest tests/integration/test_postgres.py -v
docker compose -f docker-compose.test.yml down
```

### 6. Start Services
```bash
# Terminal 1: FastAPI backend
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

# Terminal 2: Streamlit frontend
streamlit run src/frontend/app.py
```

Open http://localhost:8501

## Usage Examples

| Question | Expected SQL |
|----------|--------------|
| "How many customers?" | `SELECT COUNT(*) as customer_count FROM customers` |
| "Top 5 products by price" | `SELECT name, price FROM products ORDER BY price DESC LIMIT 5` |
| "Revenue by city" | `SELECT c.city, SUM(o.total_amount) FROM customers c JOIN orders o ON c.id = o.customer_id GROUP BY c.city ORDER BY SUM(o.total_amount) DESC` |
| "Show pending orders" | `SELECT * FROM orders WHERE status = 'pending'` |

## Running Evaluation

```bash
python run_eval.py --questions data/eval_questions.json --save eval_report.json
```

**Sample output shape:**

```
============================================================
📊 NL-to-SQL EVALUATION REPORT
============================================================

Run Date: <generated at runtime>
Total Questions: 50

📈 Overall Metrics:
  SQL Generation Accuracy:  --.-%
  Execution Success Rate:   --.-%
  Execution Accuracy:       --.-%
```

**Caveat:** 41 of the 50 questions in `data/eval_questions.json` have no `expected_approx` or `expected_row_count`, so they are credited on successful execution alone. To get a true accuracy figure, add expected values to those questions.

Exit code: `0` if execution accuracy >= 70%, `1` otherwise (CI/CD friendly).

## SQL Safety Proof

```python
from src.core.sql_validator import validate_sql

# All of these are blocked:
validate_sql("DROP TABLE customers")            # ❌ (False, "Forbidden keyword: DROP...")
validate_sql("DELETE FROM orders")              # ❌ (False, "Forbidden keyword: DELETE...")
validate_sql("SELECT 1; DROP TABLE users")       # ❌ (False, "Multiple SQL statements not allowed")
validate_sql("SELECT 1 -- DROP TABLE x")         # ❌ (False, "Forbidden keyword in comment")
validate_sql("SELECT * INTO evil FROM customers")  # ❌ (False, "SELECT ... INTO is not allowed")

# Safe queries pass:
validate_sql("SELECT * FROM customers WHERE action = 'DELETE'")   # ✅ (True, "")
validate_sql("WITH cte AS (SELECT 1) SELECT * FROM cte")         # ✅ (True, "")

# Token-aware: a string literal containing a keyword is data, not a command.
validate_sql("SELECT * FROM log WHERE note = 'please update or delete me'")  # ✅ (True, "")
```

## Project Structure

```
nl-to-sql-assistant/
├── data/
│   ├── eval_questions.json          # 50 test questions
│   ├── sample_schema.sql            # E-commerce schema
│   └── sample_data.sql              # Sample inserts
├── src/
│   ├── api/
│   │   ├── routes.py                # FastAPI endpoints
│   │   └── schemas.py               # Pydantic models
│   ├── core/
│   │   ├── nl_to_sql.py             # LangChain NL engine
│   │   ├── prompts.py               # Schema-aware prompts
│   │   ├── sql_validator.py         # Safety layer
│   │   └── query_executor.py        # DB execution + charts
│   ├── db/
│   │   ├── session.py               # SQLAlchemy session
│   │   ├── models.py                # ORM models
│   │   └── schema_inspector.py      # Schema introspection
│   ├── evaluation/
│   │   ├── evaluator.py             # Metrics calculator
│   │   └── reports.py               # Report generation
│   ├── frontend/
│   │   ├── app.py                   # Streamlit UI
│   │   ├── components.py            # Reusable UI elements
│   │   └── utils.py                 # API client
│   ├── config.py                    # Pydantic settings
│   └── main.py                      # FastAPI app
├── tests/
│   ├── unit/                        # Validator, NL, executor tests
│   └── integration/                 # API endpoint tests
├── docs/
│   └── superpowers/plans/           # Implementation plans
├── requirements.txt
└── README.md
```

## Technology Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **LLM** | LangChain + Groq/Ollama | NL understanding, SQL generation |
| **Framework** | FastAPI 0.115.4 | Async API, validation, docs |
| **Database** | PostgreSQL 16 | Relational data store |
| **ORM** | SQLAlchemy 2.0 | Query building, connections |
| **Frontend** | Streamlit 1.40 | Conversational UI |
| **Visualization** | Plotly 5.24 | Interactive charts |
| **Testing** | pytest 8.3 | Unit + integration tests |
| **Validation** | sqlparse 0.5.1 | SQL syntax analysis |

## Testing

```bash
pytest -q
```

The suite runs without any shell environment set (conftest defaults supply an in-memory SQLite database, a throwaway API key, and a mock LLM). As of the hardening pass:

```
50 passed in ~3s
```

Includes token-validator cases (literals, CTE deletes, SELECT INTO), row-cap wrapping tests, statement-timeout connect args, and API auth (401 without key, 200 with key).

## Deployment

### Local Development
```bash
uvicorn src.main:app --reload
streamlit run src/frontend/app.py
```

### Production

A multi-stage `Dockerfile` builds a non-root image (builder installs the
pinned dependency set; the runtime stage contains only interpreter + deps +
`src/`), with a healthcheck against `/api/health`:

```bash
docker build -t nl-to-sql .
docker run -p 8000:8000 --env-file .env nl-to-sql
```

Or run the full stack (API + Postgres + Redis) with compose:

```bash
cp .env.example .env       # set API_KEY and GROQ_API_KEY (or Ollama settings)
docker compose up --build
# load sample data through the published port:
psql "postgresql://nlsql:nlsql@localhost:5432/nl_to_sql" < data/sample_schema.sql
psql "postgresql://nlsql:nlsql@localhost:5432/nl_to_sql" < data/sample_data.sql
```

#### Environment variables

| Variable | Required | Default | Notes |
|----------|----------|---------|-------|
| `DATABASE_URL` | yes | — | SQLAlchemy URL; `postgresql://` enables statement timeout |
| `API_KEY` | yes | — | primary `X-API-Key` value |
| `GROQ_API_KEY` | for Groq | — | missing → `/query` degrades to 503, health/schema stay up |
| `LLM_PROVIDER` | no | `groq` | `groq` or `ollama` |
| `LLM_MODEL` | no | `llama-3.1-70b-versatile` | |
| `OLLAMA_BASE_URL` | no | `http://localhost:11434` | provider `ollama` |
| `OLLAMA_MODEL` | no | `llama3.1` | provider `ollama` |
| `STATEMENT_TIMEOUT_MS` | no | `15000` | applied per transaction via `SET LOCAL` and at connect time |
| `API_KEYS` | no | — | comma-separated extra keys; each gets its own rate-limit bucket |
| `QUERY_RATE_LIMIT` | no | `30/minute` | slowapi limit string for `POST /query`, per valid key |
| `REDIS_URL` | no | — | shared rate-limit buckets across workers; falls back to in-memory if unreachable at startup |

#### Scaling workers

`uvicorn src.main:app --workers N` is supported. Two per-process behaviors
to know: rate-limit buckets span workers only when `REDIS_URL` points at a
reachable Redis (otherwise each worker enforces its own bucket), and the
introspected-schema cache is per process with up to 60s staleness after a
schema migration. Metrics at `/api/metrics` are also per process — scrape
each worker or aggregate at the collector.

#### Production-readiness re-score (2026-10-23 pass)

The four caps the original REVIEW.md rating (8.2 → 8.7 after the hardening
pass) held on to, with the evidence closing each:

| Cap | Closed by | Evidence |
|-----|-----------|----------|
| One shared key, one team-wide 30/min bucket | `API_KEYS` + per-valid-key buckets (forged keys bucket by IP) | `tests/unit/test_auth.py`, `test_api.py::test_extra_api_keys_from_settings_are_accepted` |
| All DB tests on SQLite; Postgres behavior unproven | env-gated real-Postgres tier | `tests/integration/test_postgres.py` — 3/3 pass against Postgres 16: `pg_sleep(10)` killed at a 200ms `SET LOCAL` cap, row cap 1000, catalog introspection |
| Per-process state degrades under multiple workers | Redis-shared rate-limit buckets with in-memory fallback; schema cache documented as per-process ≤60s | `tests/unit/test_limiter_storage.py`, compose wires `REDIS_URL` |
| No metrics; latency unanswerable | `/api/metrics`: request count/latency histogram + SQL-generation and query-failure counters, route-template labels only | `tests/integration/test_metrics.py` |

Also closed from the review's remaining findings: W-06 (`SET LOCAL` per
transaction, dialect-gated), I-03 (chart type follows column semantics),
I-07 (`__all__` + `py.typed`). Tooling added: ruff gate, multi-stage
Docker image + compose stack, four-job CI (lint / offline suite /
Postgres tier / image build).

## Performance & Safety

- **Statement timeout:** Postgres connections carry `statement_timeout=15000` by default (configurable via `STATEMENT_TIMEOUT_MS`), so one runaway query cannot hold a worker indefinitely.
- **Row cap:** 1,000 rows, enforced by wrapping the query in an outer `LIMIT` subselect so a trailing `--` comment cannot disable it.
- **API authentication:** `POST /api/query` and `GET /api/schema` require an `X-API-Key` header matching `API_KEY`. `/api/health` stays anonymous for liveness probes.
- **Error handling:** Driver/SQL errors are logged server-side but not returned to API callers.
- **Evaluation accuracy:** Run `python run_eval.py` to produce `eval_report.json`. Currently 41 of 50 questions lack a ground-truth expectation, so execution-success is credited as correct until you add expected values.

## Security

- **Token-aware SQL validator:** `sql_validator.py` walks sqlparse keyword tokens rather than scanning substrings. String literals (`WHERE action = 'DELETE'`) are treated as data; comments are scanned as an injection vector; `SELECT ... INTO` is blocked because Postgres uses it to create tables.
- **API key required** on `/api/query` and `/schema` (constant-time compare); `/health` is unauthenticated for liveness.
- **Row cap cannot be bypassed** by a trailing `--` comment: the cap is an outer `SELECT * FROM (...) AS _capped LIMIT n`, not an appended clause.
- **Statement timeout** on Postgres connections stops runaway queries at the DB level.
- **No SQL, table names or driver internals** are returned on execution failure — they go to the server log only.
- LLM output is validated by `validate_sql` before reaching the executor.
- Environment-based credentials via `.env` (no hardcoding).

## Author

**Gunas** — [LinkedIn](https://linkedin.com/in/yourprofile) | [GitHub](https://github.com/yourusername)

Built to demonstrate: GenAI integration, SQL engineering, full-stack Python, safety-conscious prompt engineering, and data product thinking.

## License

MIT

---

**Why this matters for recruiters:** SQL is required in 80%+ of data and support roles. This project proves you can bridge natural language understanding (LLM), database expertise (SQL, PostgreSQL), and product engineering (FastAPI, Streamlit) while maintaining safety and measuring real-world accuracy.