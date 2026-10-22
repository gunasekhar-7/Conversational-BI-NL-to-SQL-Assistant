from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from src.config import settings


def build_connect_args(database_url: str, statement_timeout_ms: int) -> dict:
    """Connection options for the configured database.

    Only Postgres understands `statement_timeout`, and it rejects nothing else
    here, so the cap is applied just where it means something. This stops one
    runaway query (a bad join, or a model that emitted `pg_sleep`) from holding
    a worker forever.
    """
    if database_url.startswith("postgresql"):
        return {"options": f"-c statement_timeout={statement_timeout_ms}"}
    return {}


engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    connect_args=build_connect_args(
        settings.database_url,
        settings.statement_timeout_ms,
    ),
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
