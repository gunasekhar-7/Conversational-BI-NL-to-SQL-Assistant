from pydantic import BaseModel, StringConstraints
from typing import Annotated, Optional


class QueryRequest(BaseModel):
    # Bound the prompt payload: an unbounded string is a token-cost lever and
    # a prompt-injection surface. Whitespace-only questions are rejected, and
    # padding is stripped before validation so " q " counts as "q".
    question: Annotated[
        str,
        StringConstraints(min_length=1, max_length=2000, strip_whitespace=True),
    ]
    explain: bool = False


class QueryResponse(BaseModel):
    sql: str
    results: list[dict]
    columns: list[str]
    row_count: int
    error: Optional[str] = None
    chart_suggestion: Optional[str] = None
    explanation: Optional[str] = None


class SchemaResponse(BaseModel):
    schema: dict


class HealthResponse(BaseModel):
    status: str
    database: str
    # "ready" | "unavailable": lets an orchestrator tell "DB down" apart
    # from "LLM key missing" without reading logs.
    llm: str