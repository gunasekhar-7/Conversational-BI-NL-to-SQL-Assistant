import re
import sqlparse
from sqlparse import tokens as T
from typing import Tuple

__all__ = ("validate_sql",)

BLOCKED_KEYWORDS = {
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "TRUNCATE",
    "CREATE",
    "REPLACE",
    "GRANT",
    "REVOKE",
    "EXEC",
    "EXECUTE",
    "MERGE",
    "CALL",
}

ALLOWED_LEADING_KEYWORDS = {"SELECT", "WITH"}

# Row-locking clauses are rejected explicitly (REVIEW.md W-04): relying on
# UPDATE being caught as an incidental keyword made FOR SHARE slip through
# entirely, and would silently break if sqlparse ever tokenized
# "FOR UPDATE" as one unit. Cover both tokenizations: a single keyword
# starting with "FOR " and a FOR keyword followed by the modifier.
LOCK_CLAUSE_MODIFIERS = ("NO KEY UPDATE", "KEY SHARE", "UPDATE", "SHARE", "EXCLUSIVE")

BLOCKED_IN_COMMENTS = re.compile(
    r"\b(DROP|INSERT|UPDATE|DELETE|ALTER|TRUNCATE|CREATE|REPLACE|GRANT|REVOKE)\b",
    re.IGNORECASE,
)


def statements(sql: str) -> list:
    """Parse into statements, discarding ones that hold only whitespace/comments."""
    return [
        stmt
        for stmt in sqlparse.parse(sql)
        if stmt.token_first(skip_ws=True, skip_cm=True) is not None
    ]


def keyword_tokens(stmt) -> list[str]:
    """Uppercased keyword values in a statement.

    String literals, identifiers and numbers are deliberately excluded: a value
    such as `WHERE status = 'DELETE'` is data, not a command, and must not trip
    the filter.
    """
    return [
        token.value.upper()
        for token in stmt.flatten()
        if token.ttype in T.Keyword
    ]


def has_locking_clause(keywords: list[str]) -> bool:
    """True when the statement carries a FOR UPDATE / FOR SHARE lock clause.

    Works on the keyword-token sequence: string literals and identifiers are
    already excluded by `keyword_tokens`, so `WHERE text = 'FOR UPDATE'` and
    a column named `for_update` never reach here as FOR/UPDATE pairs.
    """
    for i, kw in enumerate(keywords):
        if kw.startswith("FOR "):
            if kw[4:] in LOCK_CLAUSE_MODIFIERS:
                return True
        elif kw == "FOR":
            if any(keywords[i + 1 + j] in LOCK_CLAUSE_MODIFIERS for j in range(2) if i + 1 + j < len(keywords)):
                return True
    return False


def validate_sql(sql: str) -> Tuple[bool, str]:
    """Decide whether `sql` is safe to execute.

    Rules:
      - exactly one statement, and it must start with SELECT or WITH;
      - no statement-modifying keyword anywhere in the statement's syntax;
      - no `SELECT ... INTO` (Postgres uses it to create a table);
      - no blocked keyword hidden inside a comment.

    Returns (True, "") when safe, otherwise (False, reason).
    """
    if not sql or not sql.strip():
        return False, "Empty SQL"

    parsed = statements(sql)

    if not parsed:
        return False, "Empty statement"

    if len(parsed) > 1:
        return False, "Multiple SQL statements not allowed"

    stmt = parsed[0]

    # Comments never execute, but a modifying keyword hidden in one is a
    # reliable sign of a truncation or injection attempt, so scan them on
    # purpose rather than skipping them with the rest of the noise.
    for token in stmt.flatten():
        if token.ttype in T.Comment:
            match = BLOCKED_IN_COMMENTS.search(token.value)
            if match:
                return False, "Forbidden keyword in comment"

    keywords = keyword_tokens(stmt)

    if not keywords:
        return False, "Cannot parse SQL"

    if has_locking_clause(keywords):
        return False, "FOR UPDATE / FOR SHARE locking clauses are not allowed"

    for keyword in keywords:
        if keyword in BLOCKED_KEYWORDS:
            return False, f"Forbidden keyword: {keyword}. Only SELECT queries allowed"

    if keywords[0] not in ALLOWED_LEADING_KEYWORDS:
        return False, "Only SELECT and WITH (CTE) queries allowed"

    if "INTO" in keywords:
        return False, "SELECT ... INTO is not allowed: it creates a table"

    return True, ""
