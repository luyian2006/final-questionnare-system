import pytest

from app.algorithms.jump import condition_matches, resolve_next_step


def _answer(question_id, value, answer_type="single_choice"):
    return {"question_id": question_id, "type": answer_type, "value": value}


@pytest.mark.parametrize(
    ("condition", "answer_value", "expected"),
    [
        ({"operator": "equals", "value": "a"}, "a", True),
        ({"operator": "equals", "value": "a"}, "b", False),
        ({"operator": "not_equals", "value": "a"}, "b", True),
        ({"operator": "not_equals", "value": "a"}, "a", False),
        ({"operator": "in", "values": ["a", "b"]}, "a", True),
        ({"operator": "in", "values": ["a", "b"]}, "c", False),
        ({"operator": "unknown", "value": "a"}, "a", False),
    ],
)
def test_single_choice_conditions(condition, answer_value, expected) -> None:
    assert condition_matches("single_choice", condition, answer_value) is expected


@pytest.mark.parametrize(
    ("condition", "answer_value", "expected"),
    [
        ({"operator": "contains_any", "values": ["a", "c"]}, ["a", "b"], True),
        ({"operator": "contains_any", "values": ["c"]}, ["a", "b"], False),
        ({"operator": "contains_all", "values": ["a", "b"]}, ["a", "b", "c"], True),
        ({"operator": "contains_all", "values": ["a", "c"]}, ["a", "b"], False),
        ({"operator": "equals_set", "values": ["a", "b"]}, ["b", "a"], True),
        ({"operator": "equals_set", "values": ["a", "b"]}, ["a", "b", "c"], False),
        ({"operator": "selected_count_eq", "value": 2}, ["a", "b"], True),
        ({"operator": "selected_count_eq", "value": 2}, ["a", "b", "c"], False),
        ({"operator": "selected_count_gte", "value": 2}, ["a", "b"], True),
        ({"operator": "selected_count_gte", "value": 3}, ["a", "b"], False),
        ({"operator": "selected_count_lte", "value": 2}, ["a", "b"], True),
        ({"operator": "selected_count_lte", "value": 1}, ["a", "b"], False),
        ({"operator": "unknown", "value": ["a"]}, ["a", "b"], False),
    ],
)
def test_multiple_choice_conditions(condition, answer_value, expected) -> None:
    assert condition_matches("multiple_choice", condition, answer_value) is expected


@pytest.mark.parametrize(
    ("question_type", "condition", "answer_value"),
    [
        ("single_choice", {"operator": "not_equals", "value": "a"}, None),
        ("multiple_choice", {"operator": "contains_any", "values": ["a"]}, None),
        ("multiple_choice", {"operator": "contains_any", "values": ["a"]}, "a"),
        ("multiple_choice", {"operator": "contains_all", "values": []}, ["a"]),
        ("multiple_choice", {"operator": "selected_count_gte", "value": -1}, []),
        ("text_input", {"operator": "equals", "value": "text"}, "text"),
        ("single_choice", None, "a"),
        ("multiple_choice", [], ["a"]),
    ],
)
def test_missing_or_invalid_condition_input_does_not_match(
    question_type, condition, answer_value
) -> None:
    assert condition_matches(question_type, condition, answer_value) is False


@pytest.mark.parametrize(
    ("condition", "answer_value", "expected"),
    [
        ({"operator": "lt", "value": 18}, 17, True),
        ({"operator": "lte", "value": 18}, 18, True),
        ({"operator": "gt", "value": 18}, 18, False),
        ({"operator": "gte", "value": 18}, 18, True),
        ({"operator": "equals", "value": 18}, 18, True),
        ({"operator": "between", "min": 18, "max": 60}, 60, True),
        ({"operator": "between", "min": 18, "max": 60}, 61, False),
        ({"operator": "gte", "value": 18}, True, False),
        ({"operator": "unknown", "value": 18}, 18, False),
    ],
)
def test_number_input_conditions(condition, answer_value, expected) -> None:
    assert condition_matches("number_input", condition, answer_value) is expected


def test_number_condition_handles_very_large_integer_without_overflow() -> None:
    value = 10**10000

    assert condition_matches("number_input", {"operator": "equals", "value": value}, value)


def _questions_with_jump_rules():
    return [
        {
            "question_id": "q1",
            "type": "single_choice",
            "order": 1,
            "options": [{"option_id": "a"}, {"option_id": "b"}],
            "jump_rules": [
                {
                    "rule_id": "later-rule",
                    "priority": 20,
                    "condition": {"operator": "equals", "value": "a"},
                    "target": {"type": "question", "question_id": "q3"},
                },
                {
                    "rule_id": "first-rule",
                    "priority": 10,
                    "condition": {"operator": "equals", "value": "a"},
                    "target": {"type": "question", "question_id": "q2"},
                },
            ],
        },
        {
            "question_id": "q2",
            "type": "single_choice",
            "order": 2,
            "options": [{"option_id": "a"}, {"option_id": "b"}],
        },
        {
            "question_id": "q3",
            "type": "single_choice",
            "order": 3,
            "options": [{"option_id": "a"}, {"option_id": "b"}],
            "jump_rules": [],
        },
    ]


def test_resolve_next_step_uses_default_order_when_no_rule_matches() -> None:
    questions = _questions_with_jump_rules()

    assert resolve_next_step(questions, "q1", {"q1": _answer("q1", "b")}) == {
        "action": "goto_question",
        "question_id": "q2",
        "matched_rule_id": None,
    }


def test_resolve_next_step_ends_after_last_question() -> None:
    questions = _questions_with_jump_rules()

    assert resolve_next_step(questions, "q3", {"q3": _answer("q3", "a")}) == {
        "action": "end",
        "matched_rule_id": None,
    }


def test_resolve_next_step_uses_first_matching_rule_by_priority() -> None:
    questions = _questions_with_jump_rules()

    assert resolve_next_step(questions, "q1", {"q1": _answer("q1", "a")}) == {
        "action": "goto_question",
        "question_id": "q2",
        "matched_rule_id": "first-rule",
    }


def test_resolve_next_step_does_not_run_rules_without_an_answer() -> None:
    questions = _questions_with_jump_rules()
    questions[0]["jump_rules"] = [
        {
            "rule_id": "not-equal-rule",
            "priority": 1,
            "condition": {"operator": "not_equals", "value": "a"},
            "target": {"type": "question", "question_id": "q3"},
        }
    ]

    assert resolve_next_step(questions, "q1", {}) == {
        "action": "awaiting_answer",
        "question_id": "q1",
        "matched_rule_id": None,
    }


def test_resolve_next_step_supports_end_target() -> None:
    questions = _questions_with_jump_rules()
    questions[0]["jump_rules"] = [
        {
            "rule_id": "end-rule",
            "priority": 1,
            "condition": {"operator": "equals", "value": "a"},
            "target": {"type": "end"},
        }
    ]

    assert resolve_next_step(questions, "q1", {"q1": _answer("q1", "a")}) == {
        "action": "end",
        "matched_rule_id": "end-rule",
    }


def test_resolve_next_step_rejects_unknown_current_question() -> None:
    assert resolve_next_step(_questions_with_jump_rules(), "missing", {}) == {
        "action": "error",
        "code": "unknown_current_question",
        "message": "question not found: missing",
        "question_id": "missing",
    }


def test_resolve_next_step_rejects_empty_question_list() -> None:
    assert resolve_next_step([], "q1", {}) == {
        "action": "error",
        "code": "empty_survey",
        "message": "survey has no questions",
    }


def test_resolve_next_step_handles_missing_jump_rules_field() -> None:
    questions = [
        {"question_id": "q1", "type": "single_choice", "order": 1, "options": [{"option_id": "a"}]},
        {"question_id": "q2", "type": "single_choice", "order": 2, "options": [{"option_id": "a"}]},
    ]

    assert resolve_next_step(questions, "q1", {"q1": _answer("q1", "a")}) == {
        "action": "goto_question",
        "question_id": "q2",
        "matched_rule_id": None,
    }


def test_resolve_next_step_rejects_undocumented_question_fields() -> None:
    questions = [
        {
            "id": "q1",
            "type": "single_choice",
            "order": 1,
            "options": [{"option_id": "a"}],
            "jump_rules": [
                {
                    "priority": 1,
                    "condition": {"operator": "equals", "value": "a"},
                    "next_question_id": "end",
                }
            ],
        }
    ]

    result = resolve_next_step(questions, "q1", {"q1": _answer("q1", "a")})
    assert result["action"] == "error"
    assert result["code"] == "missing_question_id"


def test_resolve_next_step_rejects_legacy_jump_target_field() -> None:
    questions = [
        {
            "question_id": "q1",
            "type": "single_choice",
            "order": 1,
            "options": [{"option_id": "a"}],
            "jump_rules": [
                {
                    "rule_id": "legacy-rule",
                    "priority": 1,
                    "condition": {"operator": "equals", "value": "a"},
                    "next_question_id": "end",
                }
            ],
        }
    ]

    result = resolve_next_step(questions, "q1", {"q1": _answer("q1", "a")})

    assert result["action"] == "error"
    assert result["code"] == "invalid_target_type"


def test_resolve_next_step_sorts_shuffled_questions_by_order() -> None:
    questions = _questions_with_jump_rules()
    questions[0]["jump_rules"] = []

    assert resolve_next_step(
        [questions[1], questions[0]],
        "q1",
        {"q1": _answer("q1", "b")},
    ) == {
        "action": "goto_question",
        "question_id": "q2",
        "matched_rule_id": None,
    }


def test_resolve_next_step_returns_structured_error_for_invalid_answer() -> None:
    result = resolve_next_step(
        _questions_with_jump_rules(),
        "q1",
        {"q1": _answer("q1", "unknown")},
    )

    assert result["action"] == "error"
    assert result["code"] == "invalid_answer_option"
    assert result["question_id"] == "q1"


def test_resolve_next_step_rejects_missing_answer_type_and_raw_scalars() -> None:
    questions = _questions_with_jump_rules()
    missing_type = resolve_next_step(
        questions,
        "q1",
        {"q1": {"question_id": "q1", "value": "a"}},
    )
    raw_value = resolve_next_step(questions, "q1", {"q1": "a"})

    assert missing_type["action"] == "error"
    assert missing_type["code"] == "invalid_answer_type"
    assert raw_value["action"] == "error"
    assert raw_value["code"] == "invalid_answer"


def test_resolve_next_step_rejects_null_jump_rules_and_duplicate_priority() -> None:
    questions = _questions_with_jump_rules()
    questions[0]["jump_rules"] = None
    assert resolve_next_step(questions, "q1", {})["code"] == "invalid_survey_definition"

    questions = _questions_with_jump_rules()
    questions[0]["jump_rules"][1]["priority"] = 20
    assert resolve_next_step(questions, "q1", {})["code"] == "duplicate_rule_priority"

    questions = _questions_with_jump_rules()
    del questions[0]["jump_rules"][0]["rule_id"]
    assert resolve_next_step(questions, "q1", {})["code"] == "invalid_survey_definition"


@pytest.mark.parametrize(
    ("options", "expected_code"),
    [
        ([], "invalid_answer_option"),
        ([{"option_id": "a"}, {"option_id": "a"}], "duplicate_option_id"),
        ([{}], "missing_option_id"),
    ],
)
def test_resolve_next_step_validates_choice_definitions(options, expected_code) -> None:
    questions = [
        {"question_id": "q1", "type": "single_choice", "order": 1, "options": options}
    ]

    result = resolve_next_step(questions, "q1", {"q1": _answer("q1", "a")})

    assert result["action"] == "error"
    assert result["code"] == expected_code
