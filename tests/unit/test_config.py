from src.db.session import build_connect_args


def test_statement_timeout_only_for_postgres():
    assert build_connect_args("postgresql://u:p@h/db", 15000) == {
        "options": "-c statement_timeout=15000"
    }
    assert build_connect_args("sqlite://", 15000) == {}


def test_statement_timeout_uses_configured_value():
    assert build_connect_args("postgresql+psycopg2://u:p@h/db", 2500) == {
        "options": "-c statement_timeout=2500"
    }
