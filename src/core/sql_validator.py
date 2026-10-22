import re
import sqlparse
from typing import Tuple


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


def validate_sql(sql: str) -> Tuple[bool, str]:
    if not sql or not sql.strip():
        return False, "Empty SQL"

    parsed = sqlparse.parse(sql)

    if len(parsed) > 1:
        return False, "Multiple SQL statements not allowed"

    stmt = parsed[0]

    if stmt.token_first(skip_ws=True, skip_cm=True) is None:
        return False, "Empty statement"

    upper_sql = sql.upper().strip()

    if ";" in sql.replace(";", "", sql.count(";") - (1 if sql.strip().endswith(";") else 0)):
        return False, "Multiple statements not allowed (extra semicolons)"

    if sql.count(";") > 1:
        return False, "Multiple statements not allowed"

    for keyword in BLOCKED_KEYWORDS:
        if re.search(r'\b' + keyword + r'\b', upper_sql):
            if upper_sql.startswith("--"):
                return False, "Only SELECT queries allowed"
            return False, f"Forbidden keyword: {keyword}. Only SELECT queries allowed"

    first_word = re.match(r'^\s*(\w+)', sql)
    if not first_word:
        return False, "Cannot parse SQL"

    first = first_word.group(1).upper()

    if first not in ("SELECT", "WITH"):
        return False, "Only SELECT and WITH (CTE) queries allowed"

    if "/*" in sql and "*/" in sql:
        if "--" in sql:
            pass

    comment_check = re.search(r'--.*?(DROP|INSERT|UPDATE|DELETE)', sql, re.IGNORECASE)
    if comment_check:
        return False, "Forbidden keyword in comment"

    return True, ""