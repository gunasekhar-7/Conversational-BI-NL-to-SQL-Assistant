from pydantic_settings import BaseSettings
from typing import Literal


class Settings(BaseSettings):
    database_url: str
    api_key: str
    groq_api_key: str | None = None
    llm_model: str = "llama-3.1-70b-versatile"
    llm_provider: Literal["groq", "ollama"] = "groq"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"
    statement_timeout_ms: int = 15000
    # Comma-separated extra API keys; each valid key gets its own rate-limit
    # bucket, so a team no longer shares one 30/min budget (REVIEW.md cap 1).
    # Empty (the default) means: only API_KEY is valid.
    api_keys: str = ""
    # slowapi limit string for POST /query; read at process start.
    query_rate_limit: str = "30/minute"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()