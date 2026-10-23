__all__ = (
    "SCHEMA_AWARE_PROMPT",
    "FEW_SHOT_EXAMPLES",
    "EXPLAIN_PROMPT",
    "build_prompt",
    "build_explain_prompt",
)

SCHEMA_AWARE_PROMPT = """You are an expert SQL query writer for PostgreSQL.

Database Schema:
{schema_description}

Rules:
- ONLY write SELECT queries. Never INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, CREATE, or any modifying statements.
- Use exact table and column names from the schema above.
- Use proper JOINs when tables are related via foreign keys.
- Use aggregate functions (COUNT, SUM, AVG, MAX, MIN) and GROUP BY when needed.
- For dates, use PostgreSQL date functions appropriately.
- Write clear, readable SQL with proper indentation.
- Return ONLY the SQL query, no explanation, no markdown code blocks.

Examples:
{few_shot}

Question: {question}

SQL Query:"""


FEW_SHOT_EXAMPLES = [
    {
        "question": "How many customers do we have?",
        "sql": "SELECT COUNT(*) as customer_count FROM customers",
    },
    {
        "question": "What are the top 5 products by price?",
        "sql": "SELECT name, price FROM products ORDER BY price DESC LIMIT 5",
    },
    {
        "question": "Show total revenue by city",
        "sql": """SELECT c.city, SUM(o.total_amount) as total_revenue
FROM customers c
JOIN orders o ON c.id = o.customer_id
GROUP BY c.city
ORDER BY total_revenue DESC""",
    },
]


EXPLAIN_PROMPT = """You are explaining a SQL query to a data analyst.

Database Schema:
{schema_description}

Question: {question}

Generated SQL:
{sql}

In one or two sentences, explain what this query does and how it answers the
question. Mention the tables it reads and any joins or filters that matter.
Do not rewrite or improve the query. Do not use markdown."""


def build_prompt(question: str, schema_description: str) -> str:
    """Compose the full SQL-generation prompt.

    All pieces — schema, rules, few-shot examples, question, generation cue —
    are assembled here so the template owns their order (REVIEW.md I-01) and
    the question appears exactly once, last, right before the cue.
    """
    few_shot = "\n\n".join(
        f"Question: {ex['question']}\nSQL: {ex['sql']}" for ex in FEW_SHOT_EXAMPLES
    )
    return SCHEMA_AWARE_PROMPT.format(
        schema_description=schema_description,
        few_shot=few_shot,
        question=question,
    )


def build_explain_prompt(question: str, sql: str, schema_description: str) -> str:
    return EXPLAIN_PROMPT.format(
        schema_description=schema_description,
        question=question,
        sql=sql,
    )