import json
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from pathlib import Path
from typing import Callable, Optional
from src.core.nl_to_sql import NLToSQL
from src.core.query_executor import execute_query
from src.db.schema_inspector import inspect_schema, format_schema_for_prompt
from src.db.session import SessionLocal, engine


class EvalItem:
    def __init__(self, id: int, category: str, question: str, expected_result_type: str,
                 expected_approx: Optional[float] = None, expected_row_count: Optional[int] = None,
                 expected_value_exact: Optional[str] = None):
        self.id = id
        self.category = category
        self.question = question
        self.expected_result_type = expected_result_type
        self.expected_approx = expected_approx
        self.expected_row_count = expected_row_count
        self.expected_value_exact = expected_value_exact


class EvalResult:
    def __init__(self, item: EvalItem, sql: str, generated: bool, executed: bool,
                 correct: bool, error: Optional[str] = None):
        self.item = item
        self.sql = sql
        self.generated = generated
        self.executed = executed
        self.correct = correct
        self.error = error


class Evaluator:
    def __init__(self, llm=None, questions_path: str = "data/eval_questions.json"):
        self.nl_engine = NLToSQL(llm=llm) if llm else NLToSQL()
        self.questions_path = questions_path
        self.schema_desc = format_schema_for_prompt(inspect_schema(engine))
        self.results: list[EvalResult] = []

    def load_questions(self) -> list[EvalItem]:
        data = json.loads(Path(self.questions_path).read_text())
        return [
            EvalItem(
                id=q["id"],
                category=q["category"],
                question=q["question"],
                expected_result_type=q["expected_result_type"],
                expected_approx=q.get("expected_approx"),
                expected_row_count=q.get("expected_row_count"),
                expected_value_exact=q.get("expected_value_exact"),
            )
            for q in data
        ]

    def evaluate_question(self, item: EvalItem) -> EvalResult:
        sql = ""
        generated = False
        executed = False
        correct = False
        error = None

        try:
            sql = self.nl_engine.generate_sql(item.question, self.schema_desc)
            generated = True
        except Exception as e:
            error = str(e)
            return EvalResult(item, sql, generated, executed, correct, error)

        db = SessionLocal()
        try:
            df, exec_error = execute_query(sql, db)

            if exec_error:
                error = exec_error
                return EvalResult(item, sql, generated, executed, correct, error)

            executed = True
            correct = self._check_correctness(df, item)
            error = None if correct else "Result mismatch"

        except Exception as e:
            error = str(e)
        finally:
            db.close()

        return EvalResult(item, sql, generated, executed, correct, error)

    def _check_correctness(self, df, item: EvalItem) -> bool:
        """Check whether the result matches the expected value(s).

        All expectations must hold simultaneously:
          - expected_row_count: exact number of rows
          - expected_approx: numeric first value within tolerance
          - expected_value_exact: string first value, exact match
        """
        # Row count check (always checked if present)
        if item.expected_row_count is not None:
            if len(df) != item.expected_row_count:
                return False

        # Numeric approx check (scalar result type only)
        if item.expected_approx is not None and item.expected_result_type == "scalar":
            if df.empty:
                return False
            first_val = df.iloc[0, 0]
            try:
                actual = float(first_val)
                if abs(actual - item.expected_approx) >= 0.05 * abs(item.expected_approx):
                    return False
            except (ValueError, TypeError):
                return False

        # Exact string check (scalar result type only)
        if item.expected_value_exact is not None and item.expected_result_type == "scalar":
            if df.empty:
                return False
            first_val = df.iloc[0, 0]
            if str(first_val).strip() != item.expected_value_exact.strip():
                return False

        return True

    def evaluate_all(
        self,
        max_workers: int = 4,
        item_timeout: float = 60.0,
        on_progress: Optional[Callable[[int, int, EvalResult], None]] = None,
    ) -> dict:
        """Evaluate every question concurrently.

        One slow LLM call must not serialize the whole run (REVIEW.md W-03):
        questions are submitted to a small pool — sized to leave headroom
        under LLM rate limits — and each is awaited with its own timeout so a
        hung call is recorded as an error instead of blocking forever.
        Results keep question order regardless of completion order.

        `on_progress(done, total, result)` fires as each question settles.
        """
        items = self.load_questions()
        total = len(items)
        results: list[Optional[EvalResult]] = [None] * total
        report = on_progress if on_progress is not None else self._print_progress

        if not items:
            self.results = []
            return self.compute_metrics()

        executor = ThreadPoolExecutor(max_workers=max_workers)
        try:
            futures = [executor.submit(self.evaluate_question, item) for item in items]
            done = 0
            for item, future in zip(items, futures):
                try:
                    result = future.result(timeout=item_timeout)
                except FuturesTimeoutError:
                    future.cancel()
                    result = EvalResult(
                        item, "", False, False, False,
                        error=f"Timed out after {item_timeout}s waiting for evaluation",
                    )
                results[done] = result
                done += 1
                report(done, total, result)
        finally:
            # Never wait on stragglers: every item already has a recorded
            # result, and blocking here would undo the timeout's purpose.
            executor.shutdown(wait=False, cancel_futures=True)

        self.results = [r for r in results if r is not None]
        return self.compute_metrics()

    @staticmethod
    def _print_progress(done: int, total: int, result: EvalResult) -> None:
        mark = "ok" if result.correct else "FAIL"
        print(f"[{done}/{total}] Q{result.item.id} {mark}", flush=True)

    def compute_metrics(self) -> dict:
        total = len(self.results)
        if total == 0:
            return {"total": 0, "sql_generation_accuracy": 0, "execution_success_rate": 0, "execution_accuracy": 0, "by_category": {}}

        generated = sum(1 for r in self.results if r.generated)
        executed = sum(1 for r in self.results if r.executed)
        correct = sum(1 for r in self.results if r.correct)

        by_category = {}
        for r in self.results:
            cat = r.item.category
            if cat not in by_category:
                by_category[cat] = {"total": 0, "correct": 0}
            by_category[cat]["total"] += 1
            if r.correct:
                by_category[cat]["correct"] += 1

        return {
            "total": total,
            "sql_generation_accuracy": generated / total,
            "execution_success_rate": executed / total,
            "execution_accuracy": correct / total,
            "by_category": {
                cat: {
                    "total": v["total"],
                    "correct": v["correct"],
                    "accuracy": v["correct"] / v["total"] if v["total"] > 0 else 0,
                }
                for cat, v in by_category.items()
            },
        }
