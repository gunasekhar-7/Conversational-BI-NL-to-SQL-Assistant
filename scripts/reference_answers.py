#!/usr/bin/env python3
"""Rebuild the sample database in SQLite and evaluate reference answers.

Reference SQL for each eval question is executed against a database built from
data/sample_schema.sql + data/sample_data.sql, and the resulting row counts and
scalar values are printed as JSON. This is how the expected_* fields in
data/eval_questions.json are derived: they are measured, not asserted.
"""
import json
import os
import sqlite3
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Reference answers. SQLite dialect for dates (strftime); everything else is
# portable SQL that also runs on PostgreSQL.
REFERENCE_SQL = {
    1: "SELECT COUNT(*) FROM customers",
    2: "SELECT name FROM products",
    3: "SELECT COUNT(*) FROM orders",
    4: "SELECT DISTINCT city FROM customers",
    5: "SELECT price FROM products WHERE name = 'Laptop Pro 15'",
    6: "SELECT name FROM products WHERE category = 'Electronics'",
    7: "SELECT DISTINCT c.name FROM customers c JOIN orders o ON o.customer_id = c.id WHERE o.status = 'pending'",
    8: "SELECT COUNT(*) FROM products WHERE stock_quantity > 0",
    9: "SELECT MIN(price) FROM products",
    10: "SELECT email FROM customers",
    11: "SELECT AVG(total_amount) FROM orders",
    12: "SELECT SUM(total_amount) FROM orders",
    13: "SELECT status, COUNT(*) AS order_count FROM orders GROUP BY status",
    14: "SELECT MAX(total_amount) FROM orders",
    15: "SELECT category, COUNT(*) AS product_count FROM products GROUP BY category",
    16: "SELECT category, AVG(price) AS avg_price FROM products GROUP BY category",
    17: "SELECT c.city, SUM(o.total_amount) AS total_revenue FROM customers c JOIN orders o ON o.customer_id = c.id GROUP BY c.city",
    18: "SELECT city FROM customers GROUP BY city ORDER BY COUNT(*) DESC LIMIT 1",
    19: "SELECT SUM(stock_quantity) FROM products",
    20: "SELECT c.name, COUNT(o.id) AS order_count FROM customers c JOIN orders o ON o.customer_id = c.id GROUP BY c.id",
    21: "SELECT o.id AS order_id, c.name AS customer_name, o.order_date, o.status, o.total_amount FROM orders o JOIN customers c ON c.id = o.customer_id",
    22: "SELECT o.id AS order_id, p.name AS product_name, oi.quantity FROM orders o JOIN order_items oi ON oi.order_id = o.id JOIN products p ON p.id = oi.product_id",
    23: "SELECT DISTINCT c.name, c.email FROM customers c JOIN orders o ON o.customer_id = c.id",
    24: "SELECT DISTINCT p.name FROM customers c JOIN orders o ON o.customer_id = c.id JOIN order_items oi ON oi.order_id = o.id JOIN products p ON p.id = oi.product_id WHERE c.name = 'Alice Johnson'",
    25: "SELECT oi.id AS item_id, p.name AS product_name, oi.quantity, oi.unit_price FROM order_items oi JOIN products p ON p.id = oi.product_id",
    26: "SELECT c.name, SUM(o.total_amount) AS total_spent FROM customers c JOIN orders o ON o.customer_id = c.id GROUP BY c.id",
    27: "SELECT p.name FROM products p WHERE p.id NOT IN (SELECT DISTINCT oi.product_id FROM order_items oi)",
    28: "SELECT c.city FROM customers c JOIN orders o ON o.customer_id = c.id GROUP BY c.city ORDER BY SUM(o.total_amount) DESC LIMIT 1",
    29: "SELECT o.id AS order_id, c.email FROM orders o JOIN customers c ON c.id = o.customer_id WHERE o.status = 'completed'",
    30: "SELECT p.name, SUM(oi.quantity) AS total_quantity_sold FROM products p JOIN order_items oi ON oi.product_id = p.id GROUP BY p.id",
    31: "SELECT name, price FROM products ORDER BY price DESC LIMIT 5",
    32: "SELECT id, customer_id, order_date, status, total_amount FROM orders WHERE strftime('%Y', order_date) = '2024'",
    33: "SELECT name, email, city FROM customers WHERE city = 'New York'",
    34: "SELECT name, price FROM products WHERE price < 50",
    35: "SELECT id, order_date, status, total_amount FROM orders ORDER BY order_date DESC LIMIT 10",
    36: "SELECT id, customer_id, order_date, total_amount FROM orders WHERE status = 'shipped'",
    37: "SELECT name, email, created_at FROM customers WHERE strftime('%Y', created_at) = '2023'",
    38: "SELECT name, stock_quantity FROM products WHERE stock_quantity > 100",
    39: "SELECT id, customer_id, total_amount FROM orders WHERE total_amount > 200",
    40: "SELECT city, COUNT(*) AS customer_count FROM customers GROUP BY city ORDER BY customer_count ASC, city ASC LIMIT 3",
    41: "SELECT c.name, AVG(o.total_amount) AS avg_order_value FROM customers c JOIN orders o ON o.customer_id = c.id GROUP BY c.id HAVING COUNT(o.id) > 1",
    42: "SELECT c.name, SUM(o.total_amount) AS total_spent FROM customers c JOIN orders o ON o.customer_id = c.id GROUP BY c.id ORDER BY total_spent DESC LIMIT 3",
    43: "SELECT strftime('%Y-%m', order_date) AS month, COUNT(*) AS order_count FROM orders WHERE strftime('%Y', order_date) = '2024' GROUP BY month ORDER BY month",
    44: "SELECT category FROM (SELECT p.category, SUM(oi.quantity * oi.unit_price) AS revenue FROM products p JOIN order_items oi ON oi.product_id = p.id GROUP BY p.category ORDER BY revenue DESC LIMIT 1)",
    45: "SELECT c.name FROM customers c JOIN orders o ON o.customer_id = c.id GROUP BY c.id HAVING SUM(o.total_amount) > (SELECT AVG(total_amount) FROM orders)",
    46: "SELECT order_date, total_amount, SUM(total_amount) OVER (ORDER BY order_date, id) AS running_total FROM orders",
    47: "SELECT c.city, AVG(o.total_amount) AS avg_order_value FROM customers c JOIN orders o ON o.customer_id = c.id GROUP BY c.city",
    48: "SELECT p.name, COUNT(*) AS times_ordered FROM products p JOIN order_items oi ON oi.product_id = p.id GROUP BY p.id HAVING COUNT(*) > 5",
    49: "SELECT 100.0 * SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) / COUNT(*) FROM orders",
    50: "SELECT c.name, c.email FROM customers c WHERE c.id NOT IN (SELECT DISTINCT o.customer_id FROM orders o)",
}

POSTGRES_REFERENCE_SQL = {k: v for k, v in REFERENCE_SQL.items()}


def build_sqlite_db():
    """Create the sample database under SQLite and return its connection."""
    schema = open(os.path.join(ROOT, "data", "sample_schema.sql")).read()
    data = open(os.path.join(ROOT, "data", "sample_data.sql")).read()

    schema = schema.replace("SERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
    schema = schema.replace("DECIMAL(10,2)", "NUMERIC(10,2)")

    path = os.path.join(tempfile.mkdtemp(), "eval.db")
    conn = sqlite3.connect(path)
    conn.executescript(schema)
    conn.executescript(data)
    conn.commit()
    return conn


def run_reference():
    conn = build_sqlite_db()
    results = {}
    for qid, sql in sorted(REFERENCE_SQL.items()):
        try:
            cur = conn.execute(sql)
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description]
            records = [dict(zip(cols, r)) for r in rows]
            results[qid] = {
                "sql": sql,
                "row_count": len(rows),
                "scalar": records[0][list(records[0])[0]] if len(records) == 1 and len(cols) == 1 else None,
                "first_rows": records[:3],
                "error": None,
            }
        except Exception as e:
            results[qid] = {"sql": sql, "error": str(e)}
    conn.close()
    return results


if __name__ == "__main__":
    results = run_reference()
    errors = {k: v["error"] for k, v in results.items() if v.get("error")}
    if errors:
        print("Reference SQL failures:", file=sys.stderr)
        for qid, err in errors.items():
            print(f"  Q{qid}: {err}", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(results, indent=2, default=str))
