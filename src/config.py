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

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()