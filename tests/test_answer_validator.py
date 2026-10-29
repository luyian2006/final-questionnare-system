import pytest

from app.algorithms.answer_validator import MISSING, validate_answer
from app.algorithms.jump import validate_submission


def _question(question_type, *, required=False, validation=None, options=None):
    question = {
        "question_id": "q1",
        "type": question_type,
        "required": required,
        "validation": validation or {},
    }
    if options is not None:
        question["options"] = [{"option_id": option} for option in options]
    return question


def _answer(question_type, value, question_id="q1"):
    return {"question_id": question_id, "type": question_type, "value": value}


def test_single_choice_requires_defined_option_id():
    question = _question("single_choice", options=["a", "b"])
    assert validate_answer(question, _answer("single_choice", "b")) is None
    assert validate_answer(question, _answer("single_choice", "x"))["code"] == "invalid_answer_option"


@pytest.mark.parametrize(
    ("validation", "value", "expected"),
    [
        ({"min_selected": 1}, ["a"], None),
        ({"min_selected": 2}, ["a"], "invalid_answer"),
        ({"max_selected": 1}, ["a", "b"], "invalid_answer"),
        ({"exact_selected": 2, "min_selected": 1}, ["a", "b"], None),
        ({"exact_selected": 2}, ["a"], "invalid_answer"),
    ],
)
def test_multiple_choice_count_constraints(validation, value, expected):
    question = _question("multiple_choice", validation=validation, options=["a", "b"])
    error = validate_answer(question, _answer("multiple_choice", value))
    assert (None if error is None else error["code"]) == expected


def test_multiple_choice_rejects_duplicates_unknowns_and_required_empty():
    question = _question("multiple_choice", required=True, options=["a", "b"])
    assert validate_answer(question, _answer("multiple_choice", ["a", "a"]))["code"] == "duplicate_answer_option"
    assert validate_answer(question, _answer("multiple_choice", ["x"]))["code"] == "invalid_answer_option"
    assert validate_answer(question, _answer("multiple_choice", []))["code"] == "invalid_answer"


def test_text_type_required_and_length_boundaries():
    question = _question("text_input", required=True, validation={"min_length": 2, "max_length": 4})
    assert validate_answer(question, _answer("text_input", "ab")) is None
    assert validate_answer(question, _answer("text_input", "abcd")) is None
    assert validate_answer(question, _answer("text_input", "a"))["code"] == "invalid_answer"
    assert validate_answer(question, _answer("text_input", "abcde"))["code"] == "invalid_answer"
    assert validate_answer(question, _answer("text_input", ""))["code"] == "invalid_answer"
    assert validate_answer(question, _answer("text_input", 10))["code"] == "invalid_answer"


def test_missing_none_and_invalid_answer_are_distinct():
    question = _question("text_input", required=True)
    assert validate_answer(question, MISSING)["code"] == "missing_required_answer"
    assert validate_answer(question, _answer("text_input", None))["code"] == "invalid_answer"
    assert validate_answer(question, _answer("text_input", "ok")) is None


@pytest.mark.parametrize(
    ("value", "validation", "expected"),
    [
        (0, {"min_value": 0, "max_value": 10}, None),
        (10, {"min_value": 0, "max_value": 10}, None),
        (-1, {"min_value": 0}, "invalid_answer"),
        (11, {"max_value": 10}, "invalid_answer"),
        (1.5, {"integer_only": True}, "invalid_answer"),
        (True, {}, "invalid_answer"),
        (float("nan"), {}, "number_not_finite"),
        (float("inf"), {}, "number_not_finite"),
        (float("-inf"), {}, "number_not_finite"),
        (10**10000, {"max_value": 100}, "invalid_answer"),
    ],
    ids=["zero-boundary", "max-boundary", "below-minimum", "above-maximum", "fraction-integer-only", "boolean-rejected", "nan-rejected", "positive-infinity-rejected", "negative-infinity-rejected", "huge-integer-rejected"],
)
def test_number_type_finite_bounds_integer_and_boolean(value, validation, expected):
    question = _question("number_input", validation=validation)
    error = validate_answer(question, _answer("number_input", value))
    assert (None if error is None else error["code"]) == expected


def test_submission_uses_answer_validation_only_on_actual_path():
    questions = [
        {
            "question_id": "q1", "type": "single_choice", "order": 1,
            "required": True, "options": [{"option_id": "skip"}, {"option_id": "next"}],
            "jump_rules": [{
                "rule_id": "skip", "priority": 1,
                "condition": {"operator": "equals", "value": "skip"},
                "target": {"type": "question", "question_id": "q3"},
            }],
        },
        {"question_id": "q2", "type": "text_input", "order": 2, "required": True, "validation": {"min_length": 2}},
        {"question_id": "q3", "type": "number_input", "order": 3, "required": True},
    ]
    result = validate_submission(questions, {
        "q1": _answer("single_choice", "skip"),
        "q3": _answer("number_input", 5, "q3"),
    })
    assert result["valid"] is True
    assert result["path"] == ["q1", "q3"]

