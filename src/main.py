from fastapi import FastAPI
from src.api.routes import router

app = FastAPI(
    title="NL-to-SQL Conversational BI Assistant",
    description="Convert natural language questions to SQL queries safely",
    version="1.0.0",
)

app.include_router(router, prefix="/api")


@app.get("/")
def root():
    return {"message": "NL-to-SQL Assistant API", "docs": "/docs"}