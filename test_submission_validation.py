import pytest

from app.algorithms.jump import validate_submission


def _option(option_id):
    return {"option_id": option_id, "label": option_id, "order": 1}


def _question(question_id, *, required=False, jump_rules=None):
    question = {
        "question_id": question_id,
        "type": "single_choice",
        "order": int(question_id[1:]),
        "required": required,
        "options": [_option("a"), _option("b")],
    }
    if jump_rules is not None:
        question["jump_rules"] = jump_rules
    return question


def _answer(question_id, value, answer_type="single_choice"):
    return {"question_id": question_id, "type": answer_type, "value": value}


def _jump(value, target_question_id, priority=1):
    return {
        "rule_id": f"to-{target_question_id}",
        "priority": priority,
        "condition": {"operator": "equals", "value": value},
        "target": {"type": "question", "question_id": target_question_id},
    }


def test_validate_submission_accepts_all_required_answers() -> None:
    questions = [_question("q1", required=True), _question("q2", required=True)]
    answers = {"q1": _answer("q1", "a"), "q2": _answer("q2", "b")}

    result = validate_submission(questions, answers)

    assert result == {
        "valid": True,
        "path": ["q1", "q2"],
        "errors": [],
        "skipped_required_questions": [],
    }


def test_validate_submission_rejects_missing_required_answer_on_path() -> None:
    questions = [_question("q1", required=True), _question("q2", required=True)]

    result = validate_submission(questions, {"q1": _answer("q1", "a")})

    assert result["valid"] is False
    assert result["path"] == ["q1", "q2"]
    assert result["errors"][0]["code"] == "missing_required_answer"
    assert result["errors"][0]["question_id"] == "q2"


def test_validate_submission_allows_required_question_skipped_by_jump() -> None:
    questions = [
        _question("q1", required=True, jump_rules=[_jump("a", "q3")]),
        _question("q2", required=True),
        _question("q3", required=True),
    ]
    answers = {"q1": _answer("q1", "a"), "q3": _answer("q3", "b")}

    result = validate_submission(questions, answers)

    assert result["valid"] is True
    assert result["path"] == ["q1", "q3"]
    assert result["skipped_required_questions"] == ["q2"]


def test_validate_submission_rejects_answer_for_skipped_question() -> None:
    questions = [
        _question("q1", required=True, jump_rules=[_jump("a", "q3")]),
        _question("q2", required=True),
        _question("q3", required=True),
    ]
    answers = {
        "q1": _answer("q1", "a"),
        "q2": _answer("q2", "a"),
        "q3": _answer("q3", "b"),
    }

    result = validate_submission(questions, answers)

    assert result["valid"] is False
    assert result["path"] == ["q1", "q3"]
    assert result["errors"][0]["code"] == "answer_not_on_path"
    assert result["errors"][0]["question_id"] == "q2"


def test_validate_submission_rejects_unknown_answer_question() -> None:
    questions = [_question("q1", required=True)]
    answers = {"q1": _answer("q1", "a"), "missing": _answer("missing", "a")}

    result = validate_submission(questions, answers)

    assert result["valid"] is False
    assert result["path"] == []
    assert result["errors"][0]["code"] == "unknown_answer_question"
    assert result["errors"][0]["question_id"] == "missing"


def test_optional_missing_answer_uses_default_order_without_running_rules() -> None:
    questions = [
        _question("q1", required=True),
        _question("q2", jump_rules=[_jump("a", "q4")]),
        _question("q3", required=True),
        _question("q4", required=True),
    ]
    answers = {
        "q1": _answer("q1", "a"),
        "q3": _answer("q3", "a"),
        "q4": _answer("q4", "b"),
    }

    result = validate_submission(questions, answers)

    assert result["valid"] is True
    assert result["path"] == ["q1", "q2", "q3", "q4"]


@pytest.mark.parametrize(
    ("first_answer", "expected_path"),
    [("a", ["q1", "q3"]), ("b", ["q1", "q2", "q3"])],
)
def test_submission_path_is_recomputed_from_submitted_answer(first_answer, expected_path) -> None:
    questions = [
        _question("q1", required=True, jump_rules=[_jump("a", "q3")]),
        _question("q2", required=False),
        _question("q3", required=True),
    ]
    answers = {"q1": _answer("q1", first_answer), "q3": _answer("q3", "a")}

    result = validate_submission(questions, answers)

    assert result["valid"] is True
    assert result["path"] == expected_path


def test_validate_submission_finishes_after_optional_last_question() -> None:
    questions = [_question("q1", required=True), _question("q2")]

    result = validate_submission(questions, {"q1": _answer("q1", "a")})

    assert result["valid"] is True
    assert result["path"] == ["q1", "q2"]


def test_validate_submission_rejects_unknown_jump_target() -> None:
    questions = [
        _question("q1", required=True, jump_rules=[_jump("a", "missing")]),
        _question("q2", required=True),
    ]

    result = validate_submission(questions, {"q1": _answer("q1", "a")})

    assert result["valid"] is False
    assert result["errors"][0]["code"] == "invalid_runtime_target"
    assert result["errors"][0]["question_id"] == "missing"


def test_validate_submission_detects_runtime_cycle() -> None:
    questions = [_question("q1", required=True, jump_rules=[_jump("a", "q1")])]

    result = validate_submission(questions, {"q1": _answer("q1", "a")})

    assert result["valid"] is False
    assert result["path"] == ["q1"]
    assert result["errors"][0]["code"] == "jump_cycle_detected"


def test_submitted_invalid_answer_is_not_reported_as_missing() -> None:
    questions = [_question("q1", required=True)]

    result = validate_submission(questions, {"q1": _answer("q1", None)})

    assert result["valid"] is False
    assert result["errors"][0]["code"] == "invalid_answer"


def test_validate_submission_rejects_empty_survey() -> None:
    result = validate_submission([], {})

    assert result["valid"] is False
    assert result["path"] == []
    assert result["errors"][0]["code"] == "empty_survey"


def test_validate_submission_sorts_shuffled_questions_by_order() -> None:
    questions = [_question("q2", required=True), _question("q1", required=True)]
    answers = {"q1": _answer("q1", "a"), "q2": _answer("q2", "b")}

    result = validate_submission(questions, answers)

    assert result["valid"] is True
    assert result["path"] == ["q1", "q2"]


@pytest.mark.parametrize(
    ("answer", "expected_code"),
    [
        ({"question_id": "q1", "value": "a"}, "invalid_answer_type"),
        ({"type": "single_choice", "value": "a"}, "invalid_answer"),
        (_answer("q1", "a", "number_input"), "invalid_answer_type"),
        ("a", "invalid_answer"),
        ({"question_id": "q1", "type": "single_choice"}, "invalid_answer"),
    ],
)
def test_submission_requires_complete_answer_objects(answer, expected_code) -> None:
    result = validate_submission([_question("q1", required=True)], {"q1": answer})

    assert result["valid"] is False
    assert result["errors"][0]["code"] == expected_code
    assert result["errors"][0]["question_id"] == "q1"


def test_submission_rejects_nonempty_answer_when_options_are_empty() -> None:
    question = _question("q1", required=True)
    question["options"] = []

    result = validate_submission([question], {"q1": _answer("q1", "a")})

    assert result["valid"] is False
    assert result["errors"][0]["code"] == "invalid_answer_option"


def test_submission_rejects_duplicate_and_unknown_choice_options() -> None:
    questions = [
        {
            "question_id": "q1",
            "type": "multiple_choice",
            "order": 1,
            "required": True,
            "options": [_option("a"), _option("b")],
        }
    ]

    duplicate = validate_submission(
        questions,
        {"q1": _answer("q1", ["a", "a"], "multiple_choice")},
    )
    unknown = validate_submission(
        questions,
        {"q1": _answer("q1", ["missing"], "multiple_choice")},
    )

    assert duplicate["errors"][0]["code"] == "duplicate_answer_option"
    assert unknown["errors"][0]["code"] == "invalid_answer_option"


@pytest.mark.parametrize(
    "value",
    [float("nan"), float("inf"), float("-inf")],
)
def test_submission_rejects_non_finite_numeric_answers(value) -> None:
    question = {
        "question_id": "q1",
        "type": "number_input",
        "order": 1,
        "required": True,
    }

    result = validate_submission(
        [question],
        {"q1": _answer("q1", value, "number_input")},
    )

    assert result["valid"] is False
    assert result["errors"][0]["code"] == "number_not_finite"


def test_submission_handles_very_large_integer_against_numeric_constraint() -> None:
    question = {
        "question_id": "q1",
        "type": "number_input",
        "order": 1,
        "required": True,
        "validation": {"max_value": 100, "integer_only": True},
    }

    result = validate_submission(
        [question],
        {"q1": _answer("q1", 10**10000, "number_input")},
    )

    assert result["valid"] is False
    assert result["errors"][0]["code"] == "invalid_answer"


@pytest.mark.parametrize(
    ("questions", "expected_code"),
    [
        ([_question("q1"), {"type": "single_choice", "order": 2}], "missing_question_id"),
        ([_question("q1"), _question("q1")], "duplicate_question_id"),
        ([dict(_question("q1"), order=None)], "invalid_question_order"),
        ([dict(_question("q1"), order=1), dict(_question("q2"), order=1)], "duplicate_question_order"),
    ],
)
def test_submission_rejects_invalid_question_identity_or_order(questions, expected_code) -> None:
    result = validate_submission(questions, {})

    assert result["valid"] is False
    assert result["path"] == []
    assert result["errors"][0]["code"] == expected_code


def test_submission_rejects_null_jump_rules_and_duplicate_rule_priority() -> None:
    question = _question("q1", required=True)
    question["jump_rules"] = None
    result = validate_submission([question], {"q1": _answer("q1", "a")})
    assert result["errors"][0]["code"] == "invalid_survey_definition"

    question = _question(
        "q1",
        required=True,
        jump_rules=[_jump("a", "q1"), _jump("b", "q1")],
    )
    question["jump_rules"][1]["priority"] = question["jump_rules"][0]["priority"]
    result = validate_submission([question], {"q1": _answer("q1", "a")})
    assert result["errors"][0]["code"] == "duplicate_rule_priority"


def test_submission_rejects_invalid_jump_target_type() -> None:
    question = _question("q1", required=True, jump_rules=[_jump("a", "q1")])
    question["jump_rules"][0]["target"] = {"type": "next"}

    result = validate_submission([question], {"q1": _answer("q1", "a")})

    assert result["valid"] is False
    assert result["errors"][0]["code"] == "invalid_target_type"


def test_submission_honors_explicit_max_jump_steps_limit() -> None:
    questions = [_question("q1", required=True), _question("q2", required=True)]
    answers = {"q1": _answer("q1", "a"), "q2": _answer("q2", "b")}

    result = validate_submission(questions, answers, max_jump_steps=1)

    assert result["valid"] is False
    assert result["path"] == ["q1"]
    assert result["errors"][0]["code"] == "max_jump_steps_exceeded"


def test_submission_reports_cycle_separately_from_step_limit() -> None:
    questions = [_question("q1", required=True, jump_rules=[_jump("a", "q1")])]

    result = validate_submission(questions, {"q1": _answer("q1", "a")})

    assert result["valid"] is False
    assert result["path"] == ["q1"]
    assert result["errors"][0]["code"] == "jump_cycle_detected"
