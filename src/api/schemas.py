from pydantic import BaseModel
from typing import Optional


class QueryRequest(BaseModel):
    question: str


class QueryResponse(BaseModel):
    sql: str
    results: list[dict]
    columns: list[str]
    row_count: int
    error: Optional[str] = None
    chart_suggestion: Optional[str] = None


class SchemaResponse(BaseModel):
    schema: dict


class HealthResponse(BaseModel):
    status: str
    database: str