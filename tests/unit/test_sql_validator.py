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
    assert "SELECT" in error.lower()


def test_blocks_update():
    sql = "UPDATE customers SET name = 'hacked'"
    is_safe, error = validate_sql(sql)
    assert not is_safe
    assert "SELECT" in error.lower()


def test_blocks_delete():
    sql = "DELETE FROM customers"
    is_safe, error = validate_sql(sql)
    assert not is_safe
    assert "SELECT" in error.lower()


def test_blocks_drop():
    sql = "DROP TABLE customers"
    is_safe, error = validate_sql(sql)
    assert not is_safe
    assert "SELECT" in error.lower()


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