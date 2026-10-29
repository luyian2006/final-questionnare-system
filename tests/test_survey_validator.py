import copy

import pytest

from app.algorithms.survey_validator import validate_survey_definition


def _question(question_id="q1", order=1, *, kind="single_choice", rules=None):
    question = {
        "question_id": question_id,
        "type": kind,
        "title": question_id,
        "required": False,
        "order": order,
        "validation": {},
        "jump_rules": rules or [],
    }
    if kind in {"single_choice", "multiple_choice"}:
        question["options"] = [
            {"option_id": "a", "label": "A", "order": 1},
            {"option_id": "b", "label": "B", "order": 2},
        ]
    return question


def _rule(target, condition=None, priority=1):
    return {
        "rule_id": "r1",
        "priority": priority,
        "condition": condition or {"operator": "equals", "value": "a"},
        "target": target,
    }


def test_valid_questionnaire_and_forward_jump_pass_publish_validation():
    questions = [_question("q1", 1, rules=[_rule({"type": "question", "question_id": "q3"})]),
                 _question("q2", 2), _question("q3", 3)]
    assert validate_survey_definition(questions) == {"valid": True, "errors": []}


def test_choice_jump_condition_is_validated_against_its_own_question_options():
    questions = [
        _question("choice", 1, rules=[_rule({"type": "end"})]),
        _question("text", 2, kind="text_input"),
    ]

    assert validate_survey_definition(questions) == {"valid": True, "errors": []}


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda qs: qs.append(copy.deepcopy(qs[0])), "duplicate_question_id"),
        (lambda qs: qs[1].update(order=1), "duplicate_question_order"),
        (lambda qs: qs[0].update(question_id=""), "missing_question_id"),
        (lambda qs: qs[0]["options"][1].update(option_id="a"), "duplicate_option_id"),
        (lambda qs: qs[0]["options"][0].pop("option_id"), "missing_option_id"),
    ],
)
def test_publish_validator_rejects_identity_and_option_errors(mutate, expected):
    questions = [_question(), _question("q2", 2)]
    mutate(questions)
    result = validate_survey_definition(questions)
    assert result["valid"] is False
    assert result["errors"][0]["code"] == expected


def test_publish_validator_rejects_duplicate_priority_incompatible_condition_and_target():
    questions = [_question(rules=[_rule({"type": "end"}), _rule({"type": "end"}, priority=1)])]
    result = validate_survey_definition(questions)
    assert result["errors"][0]["code"] == "duplicate_rule_priority"

    questions = [_question(rules=[_rule({"type": "end"}, {"operator": "contains_any", "values": ["a"]})])]
    assert validate_survey_definition(questions)["errors"][0]["code"] == "unsupported_operator_for_question_type"

    questions = [_question(rules=[_rule({"type": "question", "question_id": "missing"})])]
    assert validate_survey_definition(questions)["errors"][0]["code"] == "invalid_jump_target"


@pytest.mark.parametrize(
    ("condition", "expected"),
    [
        ({"operator": "in", "values": []}, "empty_condition_values"),
        ({"operator": "in", "values": ["unknown"]}, "invalid_condition_option"),
    ],
)
def test_publish_validator_rejects_invalid_choice_conditions(condition, expected):
    result = validate_survey_definition([_question(rules=[_rule({"type": "end"}, condition)])])
    assert result["errors"][0]["code"] == expected


def test_publish_validator_rejects_bad_numeric_conditions_and_cycle():
    questions = [_question(kind="number_input", rules=[_rule({"type": "end"}, {"operator": "between", "min": 5, "max": 2})])]
    assert validate_survey_definition(questions)["errors"][0]["code"] == "invalid_numeric_range"

    questions = [
        _question("q1", 1),
        _question("q2", 2, rules=[_rule({"type": "question", "question_id": "q1"})]),
    ]
    result = validate_survey_definition(questions)
    assert result["valid"] is False
    assert result["errors"][0]["code"] == "jump_cycle_detected"


def test_publish_validator_reports_malformed_jump_rules_and_empty_survey():
    assert validate_survey_definition([])["errors"][0]["code"] == "empty_survey"
    question = _question()
    question["jump_rules"] = None
    assert validate_survey_definition([question])["errors"][0]["code"] == "invalid_survey_definition"
