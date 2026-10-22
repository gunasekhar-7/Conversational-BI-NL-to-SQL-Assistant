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


def build_prompt(question: str, schema_description: str) -> str:
    return SCHEMA_AWARE_PROMPT.format(
        schema_description=schema_description,
        question=question,
    )