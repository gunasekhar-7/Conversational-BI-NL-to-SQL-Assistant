from sqlalchemy import inspect


def inspect_schema(engine) -> dict:
    inspector = inspect(engine)
    schema = {}

    for table_name in inspector.get_table_names():
        columns = inspector.get_columns(table_name)
        foreign_keys = inspector.get_foreign_keys(table_name)
        pk = inspector.get_pk_constraint(table_name)

        schema[table_name] = {
            "columns": [
                {"name": c["name"], "type": str(c["type"])} for c in columns
            ],
            "primary_key": pk.get("constrained_columns", []),
            "foreign_keys": [
                {
                    "constrained_columns": fk["constrained_columns"],
                    "referred_table": fk["referred_table"],
                    "referred_columns": fk["referred_columns"],
                }
                for fk in foreign_keys
            ],
        }

    return schema


def format_schema_for_prompt(schema: dict) -> str:
    lines = []
    for table, info in schema.items():
        lines.append(f"Table: {table}")
        for col in info["columns"]:
            marker = " (PK)" if col["name"] in info["primary_key"] else ""
            lines.append(f"  - {col['name']}: {col['type']}{marker}")
        for fk in info["foreign_keys"]:
            lines.append(
                f"  FK: {', '.join(fk['constrained_columns'])} -> "
                f"{fk['referred_table']}({', '.join(fk['referred_columns'])})"
            )
        lines.append("")
    return "\n".join(lines)