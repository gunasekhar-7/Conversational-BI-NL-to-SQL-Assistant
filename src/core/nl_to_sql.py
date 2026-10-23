from langchain_groq import ChatGroq
from langchain_ollama import OllamaLLM
from langchain.schema import HumanMessage, SystemMessage
from src.core.prompts import build_prompt, build_explain_prompt, FEW_SHOT_EXAMPLES
from src.config import settings
from src.core.sql_validator import validate_sql
import re


class NLToSQL:
    def __init__(self, llm=None):
        if llm:
            self.llm = llm
        else:
            self._init_llm()

    def _init_llm(self):
        if settings.llm_provider == "groq":
            if not settings.groq_api_key:
                raise ValueError("GROQ_API_KEY not set for Groq provider")
            self.llm = ChatGroq(
                model=settings.llm_model,
                api_key=settings.groq_api_key,
                temperature=0,
            )
        elif settings.llm_provider == "ollama":
            self.llm = OllamaLLM(
                model=settings.ollama_model,
                base_url=settings.ollama_base_url,
            )
        else:
            raise ValueError(f"Unknown LLM provider: {settings.llm_provider}")

    def generate_sql(self, question: str, schema_description: str) -> str:
        few_shot = "\n".join(
            f"Q: {ex['question']}\nSQL: {ex['sql']}" for ex in FEW_SHOT_EXAMPLES
        )

        prompt = build_prompt(question, schema_description)

        few_shot_block = f"\n\nExamples:\n{few_shot}\n\nQuestion: {question}\nSQL:"

        full_prompt = prompt + few_shot_block

        messages = [
            SystemMessage(content="You are a PostgreSQL expert. Output only SQL, nothing else."),
            HumanMessage(content=full_prompt),
        ]

        response = self.llm.invoke(messages)
        raw = response.content if hasattr(response, 'content') else str(response)

        sql = self._clean_sql(raw)

        is_safe, error = validate_sql(sql)
        if not is_safe:
            raise ValueError(f"Generated unsafe SQL: {error}")

        return sql

    def explain(self, question: str, sql: str, schema_description: str) -> str:
        """Return a short plain-language description of an already-validated query.

        This is a separate call from generate_sql so the SQL prompt keeps its
        "output only SQL" contract. The explanation is never executed and is
        bounded so it stays one or two sentences.
        """
        prompt = build_explain_prompt(question, sql, schema_description)

        messages = [
            SystemMessage(content="You explain SQL to analysts in plain language."),
            HumanMessage(content=prompt),
        ]

        response = self.llm.invoke(messages)
        raw = response.content if hasattr(response, 'content') else str(response)

        return re.sub(r'\s+', ' ', raw).strip()[:600]

    def _clean_sql(self, raw: str) -> str:
        sql = raw.strip()

        sql = re.sub(r'^```sql\s*\n?', '', sql, flags=re.IGNORECASE)
        sql = re.sub(r'\n?```\s*$', '', sql)

        sql = re.sub(r'^(SQL Query:|SQL:)\s*', '', sql, flags=re.IGNORECASE)

        sql = sql.strip()

        if sql.endswith(';'):
            sql = sql[:-1]

        return sql