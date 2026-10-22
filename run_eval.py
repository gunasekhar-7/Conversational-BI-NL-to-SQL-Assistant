#!/usr/bin/env python3
"""Run NL-to-SQL evaluation suite over 50 test questions."""
import argparse
import sys
from src.evaluation.evaluator import Evaluator
from src.evaluation.reports import print_report, save_report


def main():
    parser = argparse.ArgumentParser(description="Evaluate NL-to-SQL accuracy")
    parser.add_argument("--questions", default="data/eval_questions.json", help="Path to questions JSON")
    parser.add_argument("--save", default="eval_report.json", help="Save JSON report to file")
    parser.add_argument("--no-save", action="store_true", help="Skip saving report file")
    args = parser.parse_args()

    print("Loading evaluator...")
    try:
        evaluator = Evaluator(questions_path=args.questions)
    except Exception as e:
        print(f"Failed to initialize evaluator: {e}", file=sys.stderr)
        sys.exit(1)

    print("Running evaluation on 50 questions...")
    metrics = evaluator.evaluate_all()

    print_report(metrics, evaluator.results)

    if not args.no_save:
        save_report(metrics, evaluator.results, filename=args.save)

    exit_code = 0 if metrics["execution_accuracy"] >= 0.7 else 1
    sys.exit(exit_code)


if __name__ == "__main__":
    main()