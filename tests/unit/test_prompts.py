"""Prompt composition lives entirely in prompts.py (REVIEW.md I-01)."""

from src.core.prompts import FEW_SHOT_EXAMPLES, build_prompt


QUESTION = "Which carrier had the fastest delivery in March?"
SCHEMA = "Table: orders (id, carrier_id, delivered_at)"


def test_question_appears_exactly_once():
    prompt = build_prompt(QUESTION, SCHEMA)

    assert prompt.count(QUESTION) == 1, "the question must not be duplicated"


def test_prompt_includes_few_shot_examples():
    prompt = build_prompt(QUESTION, SCHEMA)

    for example in FEW_SHOT_EXAMPLES:
        assert example["sql"] in prompt, "each few-shot SQL belongs in the prompt"


def test_prompt_ends_with_generation_cue_after_question():
    prompt = build_prompt(QUESTION, SCHEMA)

    question_pos = prompt.rindex(QUESTION)
    cue_pos = prompt.rindex("SQL Query:")
    assert cue_pos > question_pos, "the question must be the last thing before the cue"


def test_schema_appears_before_question():
    prompt = build_prompt(QUESTION, SCHEMA)

    assert prompt.index(SCHEMA) < prompt.index(QUESTION)
