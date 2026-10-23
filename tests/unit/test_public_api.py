"""Packaging hygiene: core modules declare their public API (REVIEW.md I-07)."""

from pathlib import Path

import src
from src.core import nl_to_sql, prompts, query_executor, sql_validator


def test_core_modules_declare_public_api():
    for module in (sql_validator, query_executor, nl_to_sql, prompts):
        assert hasattr(module, "__all__"), f"{module.__name__} has no __all__"
        assert module.__all__, f"{module.__name__} has an empty __all__"
        for name in module.__all__:
            assert hasattr(module, name), f"{module.__name__}.__all__ names missing {name}"


def test_py_typed_marker_exists():
    assert Path(src.__file__).parent.joinpath("py.typed").exists()
