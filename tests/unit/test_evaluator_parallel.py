import time

from src.evaluation.evaluator import EvalItem, EvalResult, Evaluator


def make_evaluator():
    """Evaluator with mocked LLM/schema (no DB or API needed)."""
    from unittest.mock import MagicMock, patch

    with patch("src.evaluation.evaluator.NLToSQL", return_value=MagicMock()), \
         patch("src.evaluation.evaluator.inspect_schema", return_value={}), \
         patch("src.evaluation.evaluator.format_schema_for_prompt", return_value=""):
        ev = Evaluator(llm=MagicMock())
    return ev


def make_items(n):
    return [EvalItem(i, "cat", f"question {i}", "list", expected_row_count=1) for i in range(n)]


def test_evaluate_all_runs_questions_concurrently():
    ev = make_evaluator()
    items = make_items(6)
    ev.load_questions = lambda: items

    def slow(item):
        time.sleep(0.3)
        return EvalResult(item, "SELECT 1", True, True, True)

    ev.evaluate_question = slow

    start = time.monotonic()
    metrics = ev.evaluate_all(max_workers=6, item_timeout=10.0)
    elapsed = time.monotonic() - start

    assert metrics["total"] == 6
    # Sequential would take >= 1.8s; allow generous CI overhead but require
    # clear evidence of overlap.
    assert elapsed < 1.2, f"took {elapsed:.2f}s — questions did not overlap"


def test_evaluate_all_preserves_question_order():
    ev = make_evaluator()
    items = make_items(5)
    ev.load_questions = lambda: items

    # First question sleeps longest: completion order != submission order.
    def vary(item):
        time.sleep(0.25 if item.id == 0 else 0.01)
        return EvalResult(item, "SELECT 1", True, True, item.id % 2 == 0)

    ev.evaluate_question = vary

    metrics = ev.evaluate_all(max_workers=5, item_timeout=10.0)

    assert metrics["total"] == 5
    assert [r.item.id for r in ev.results] == [0, 1, 2, 3, 4]


def test_evaluate_all_times_out_hung_item():
    ev = make_evaluator()
    items = make_items(1)
    ev.load_questions = lambda: items

    def hang(item):
        time.sleep(0.8)
        return EvalResult(item, "SELECT 1", True, True, True)

    ev.evaluate_question = hang

    metrics = ev.evaluate_all(max_workers=2, item_timeout=0.05)

    assert metrics["total"] == 1
    assert metrics["execution_accuracy"] == 0
    assert ev.results[0].error is not None
    assert "timed out" in ev.results[0].error.lower()
    assert ev.results[0].correct is False


def test_evaluate_all_reports_progress():
    ev = make_evaluator()
    items = make_items(3)
    ev.load_questions = lambda: items

    ev.evaluate_question = lambda item: EvalResult(item, "SELECT 1", True, True, True)

    seen = []
    ev.evaluate_all(
        max_workers=3,
        item_timeout=10.0,
        on_progress=lambda done, total, result: seen.append((done, total)),
    )

    assert [d for d, _ in seen] == [1, 2, 3]
    assert all(t == 3 for _, t in seen)
