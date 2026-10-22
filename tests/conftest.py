import os

# Ensure src.config can be imported in test runs without any shell env setup.
# Real deployments set these via .env; tests use an in-memory SQLite database
# and never call a live LLM (LLM construction is mocked or overridden).
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("GROQ_API_KEY", "test-placeholder")