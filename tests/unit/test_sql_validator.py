import pytest
from src.core.sql_validator import validate_sql


def test_allows_simple_select():
    sql = "SELECT * FROM customers"
    is_safe, error = validate_sql(sql)
    assert is_safe
    assert error == ""


def test_allows_select_with_where():
    sql = "SELECT name, email FROM customers WHERE city = 'New York'"
    is_safe, error = validate_sql(sql)
    assert is_safe
    assert error == ""


def test_blocks_insert():
    sql = "INSERT INTO customers (name) VALUES ('hacker')"
    is_safe, error = validate_sql(sql)
    assert not is_safe
    assert "select" in error.lower()


def test_blocks_update():
    sql = "UPDATE customers SET name = 'hacked'"
    is_safe, error = validate_sql(sql)
    assert not is_safe
    assert "select" in error.lower()


def test_blocks_delete():
    sql = "DELETE FROM customers"
    is_safe, error = validate_sql(sql)
    assert not is_safe
    assert "select" in error.lower()


def test_blocks_drop():
    sql = "DROP TABLE customers"
    is_safe, error = validate_sql(sql)
    assert not is_safe
    assert "select" in error.lower()


def test_blocks_alter():
    sql = "ALTER TABLE customers ADD COLUMN hack INT"
    is_safe, error = validate_sql(sql)
    assert not is_safe


def test_blocks_truncate():
    sql = "TRUNCATE TABLE customers"
    is_safe, error = validate_sql(sql)
    assert not is_safe


def test_blocks_create():
    sql = "CREATE TABLE hack (id INT)"
    is_safe, error = validate_sql(sql)
    assert not is_safe


def test_blocks_multi_statement():
    sql = "SELECT 1; DROP TABLE customers"
    is_safe, error = validate_sql(sql)
    assert not is_safe


def test_blocks_comment_injection():
    sql = "SELECT 1 -- ; DROP TABLE customers"
    is_safe, error = validate_sql(sql)
    assert not is_safe


def test_allows_cte():
    sql = "WITH cte AS (SELECT 1 as x) SELECT * FROM cte"
    is_safe, error = validate_sql(sql)
    assert is_safe
    assert error == ""


def test_blocks_union_with_dml():
    sql = "SELECT 1 UNION SELECT 2; DELETE FROM customers"
    is_safe, error = validate_sql(sql)
    assert not is_safe


def test_blocks_case_insensitive():
    sql = "dRoP tAbLe customers"
    is_safe, error = validate_sql(sql)
    assert not is_safe


def test_allows_blocked_keyword_inside_string_literal():
    sql = "SELECT * FROM activity_log WHERE action = 'DELETE'"
    assert validate_sql(sql) == (True, "")


def test_allows_multiple_keywords_inside_literals():
    sql = "SELECT name FROM customers WHERE note = 'please update or create'"
    assert validate_sql(sql) == (True, "")


def test_allows_identifier_containing_keyword():
    sql = "SELECT delete_flag, update_status FROM jobs"
    assert validate_sql(sql) == (True, "")


def test_blocks_select_into():
    is_safe, error = validate_sql("SELECT * INTO evil_copy FROM customers")
    assert not is_safe
    assert "INTO" in error


def test_blocks_delete_returning_cte():
    sql = "WITH d AS (DELETE FROM customers RETURNING *) SELECT * FROM d"
    is_safe, error = validate_sql(sql)
    assert not is_safe
    assert "DELETE" in error


def test_blocks_for_update():
    sql = "SELECT * FROM customers FOR UPDATE"
    assert not validate_sql(sql)[0]


def test_blocks_for_update_with_explicit_reason():
    """The lock clause must be caught by explicit detection, not by luck
    (UPDATE happening to be a keyword token) — see REVIEW.md W-04."""
    is_safe, error = validate_sql("SELECT * FROM customers FOR UPDATE")
    assert not is_safe
    assert "lock" in error.lower()


def test_blocks_for_share():
    is_safe, error = validate_sql("SELECT * FROM customers FOR SHARE")
    assert not is_safe
    assert "lock" in error.lower()


def test_blocks_for_update_of_table():
    is_safe, error = validate_sql("SELECT * FROM customers FOR UPDATE OF orders")
    assert not is_safe
    assert "lock" in error.lower()


def test_allows_locking_clause_inside_string_literal():
    sql = "SELECT * FROM docs WHERE text = 'SELECT FOR UPDATE'"
    assert validate_sql(sql) == (True, "")


def test_allows_column_named_for_update():
    sql = "SELECT for_update FROM audit"
    assert validate_sql(sql) == (True, "")


def test_allows_trailing_semicolon():
    is_safe, error = validate_sql("SELECT 1;")
    assert is_safe
    assert error == ""