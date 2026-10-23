import json
from pathlib import Path
from unittest.mock import MagicMock, patch


from src.evaluation.evaluator import EvalItem, Evaluator


def make_evaluator():
    """Build an evaluator with a mock LLM and mocked engine."""
    mock_llm = MagicMock()
    mock_engine = MagicMock()
    mock_engine.format_schema_for_prompt.return_value = "dummy schema"
    with patch("src.evaluation.evaluator.NLToSQL", return_value=mock_llm), \
         patch("src.evaluation.evaluator.inspect_schema", return_value={}), \
         patch("src.evaluation.evaluator.format_schema_for_prompt", return_value=""):
        ev = Evaluator(llm=mock_llm)
    return ev, mock_llm


def test_check_correctness_row_count():
    import pandas as pd
    ev, _ = make_evaluator()
    df = pd.DataFrame({"a": [1, 2, 3]})
    item = EvalItem(1, "test", "q", "list", expected_row_count=3)
    assert ev._check_correctness(df, item) is True
    item_bad = EvalItem(2, "test", "q", "list", expected_row_count=4)
    assert ev._check_correctness(df, item_bad) is False


def test_check_correctness_approx_scalar():
    import pandas as pd
    ev, _ = make_evaluator()
    df = pd.DataFrame({"val": [50.0]})
    item = EvalItem(1, "test", "q", "scalar", expected_approx=50.0, expected_row_count=1)
    assert ev._check_correctness(df, item) is True
    df_wrong = pd.DataFrame({"val": [40.0]})
    item_wrong = EvalItem(2, "test", "q", "scalar", expected_approx=50.0, expected_row_count=1)
    assert ev._check_correctness(df_wrong, item_wrong) is False


def test_check_correctness_exact_string():
    import pandas as pd
    ev, _ = make_evaluator()
    df = pd.DataFrame({"city": ["New York"]})
    item = EvalItem(1, "test", "q", "scalar", expected_value_exact="New York", expected_row_count=1)
    assert ev._check_correctness(df, item) is True
    df_wrong = pd.DataFrame({"city": ["Boston"]})
    item_wrong = EvalItem(2, "test", "q", "scalar", expected_value_exact="New York", expected_row_count=1)
    assert ev._check_correctness(df_wrong, item_wrong) is False


def test_check_correctness_empty_df_fails_approx():
    import pandas as pd
    ev, _ = make_evaluator()
    df = pd.DataFrame()
    item = EvalItem(1, "test", "q", "scalar", expected_approx=50.0, expected_row_count=1)
    assert ev._check_correctness(df, item) is False


def test_all_questions_have_expectation():
    data = json.loads(Path("data/eval_questions.json").read_text())
    missing = [
        q["id"] for q in data
        if q.get("expected_approx") is None
        and q.get("expected_row_count") is None
        and q.get("expected_value_exact") is None
    ]
    assert missing == [], f"Questions without expectation: {missing}"


def test_scalar_questions_have_approx_or_exact():
    data = json.loads(Path("data/eval_questions.json").read_text())
    for q in data:
        if q["expected_result_type"] == "scalar":
            assert q.get("expected_approx") is not None or q.get("expected_value_exact") is not None, \
                f"Q{q['id']} is scalar but has no numeric or exact expectation"


def test_list_grouped_questions_have_row_count():
    data = json.loads(Path("data/eval_questions.json").read_text())
    for q in data:
        if q["expected_result_type"] in ("list", "grouped"):
            assert q.get("expected_row_count") is not None, \
                f"Q{q['id']} is {q['expected_result_type']} but has no expected_row_count"
