from src.evaluation.evaluator import EvalResult, Evaluator
import json
from datetime import datetime


def print_report(metrics: dict, results: list[EvalResult]):
    print("\n" + "=" * 70)
    print("📊 NL-to-SQL EVALUATION REPORT")
    print("=" * 70)
    print(f"\nRun Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Total Questions: {metrics['total']}")
    print(f"\n📈 Overall Metrics:")
    print(f"  SQL Generation Accuracy:  {metrics['sql_generation_accuracy']:.1%}")
    print(f"  Execution Success Rate:   {metrics['execution_success_rate']:.1%}")
    print(f"  Execution Accuracy:       {metrics['execution_accuracy']:.1%}")

    print(f"\n📋 By Category:")
    for cat, data in metrics.get("by_category", {}).items():
        print(f"  {cat:20s} {data['correct']}/{data['total']} ({data['accuracy']:.1%})")

    print(f"\n🔍 Detailed Failures:")
    for r in results:
        if not r.correct:
            print(f"\n  ✗ Q{r.item.id} [{r.item.category}]: {r.item.question}")
            if r.sql:
                print(f"    SQL: {r.sql[:100]}")
            if r.error:
                print(f"    Error: {r.error}")

    print("=" * 70)


def save_report(metrics: dict, results: list[EvalResult], filename: str = "eval_report.json"):
    report = {
        "timestamp": datetime.now().isoformat(),
        "metrics": metrics,
        "failures": [
            {
                "id": r.item.id,
                "category": r.item.category,
                "question": r.item.question,
                "sql": r.sql,
                "error": r.error,
            }
            for r in results
            if not r.correct
        ],
    }
    with open(filename, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\n💾 Report saved to {filename}")