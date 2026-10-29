import math
from collections.abc import Mapping, Sequence
from fractions import Fraction
from numbers import Integral, Real

from app.algorithms.answer_validator import validate_answer as _validate_answer


def _is_finite_number(value):
    if not isinstance(value, Real) or isinstance(value, bool):
        return False
    if isinstance(value, (Integral, Fraction)):
        return True
    try:
        return math.isfinite(value)
    except (OverflowError, TypeError, ValueError):
        return False


def _condition_values(condition):
    """Read the documented `values` field for set-valued conditions."""
    return condition.get("values")


def condition_matches(question_type, condition, answer_value):
    """Return whether one already-validated answer matches a jump condition.

    Invalid runtime input and unsupported operators do not match. Survey publishing is
    responsible for rejecting those configurations before they reach this function.
    """
    if not isinstance(condition, Mapping) or answer_value is None:
        return False

    operator = condition.get("operator")
    if not isinstance(operator, str):
        return False

    if question_type == "single_choice":
        if isinstance(answer_value, (Mapping, list, tuple, set)):
            return False

        target_value = condition.get("value")
        if operator == "equals":
            return answer_value == target_value
        if operator == "not_equals":
            return target_value is not None and answer_value != target_value
        if operator == "in":
            target_values = _condition_values(condition)
            if not isinstance(target_values, (list, tuple, set)):
                return False
            return answer_value in target_values

    elif question_type == "multiple_choice":
        if not isinstance(answer_value, (list, tuple, set)):
            return False

        try:
            selected = set(answer_value)
        except TypeError:
            return False

        if operator in {"contains_any", "contains_all", "equals_set"}:
            target_values = _condition_values(condition)
            if not isinstance(target_values, (list, tuple, set)) or not target_values:
                return False
            try:
                expected = set(target_values)
            except TypeError:
                return False

            if operator == "contains_any":
                return bool(selected & expected)
            if operator == "contains_all":
                return expected.issubset(selected)
            return selected == expected

        target_value = condition.get("value")
        if (
            not isinstance(target_value, int)
            or isinstance(target_value, bool)
            or target_value < 0
        ):
            return False
        if operator == "selected_count_eq":
            return len(answer_value) == target_value
        if operator == "selected_count_gte":
            return len(answer_value) >= target_value
        if operator == "selected_count_lte":
            return len(answer_value) <= target_value

    elif question_type == "number_input":
        if not _is_finite_number(answer_value):
            return False

        if operator == "between":
            minimum = condition.get("min")
            maximum = condition.get("max")
            if not _is_finite_number(minimum) or not _is_finite_number(maximum):
                return False
            return minimum <= answer_value <= maximum

        target_value = condition.get("value")
        if not _is_finite_number(target_value):
            return False
        if operator == "lt":
            return answer_value < target_value
        if operator == "lte":
            return answer_value <= target_value
        if operator == "gt":
            return answer_value > target_value
        if operator == "gte":
            return answer_value >= target_value
        if operator == "equals":
            return answer_value == target_value

    # Text input and unknown question types are not jump-rule sources in version 1.
    return False


def _question_id(question):
    if not isinstance(question, Mapping):
        raise ValueError("Question definitions must be mappings")
    if "question_id" not in question:
        raise ValueError("Question definition is missing question_id")
    return question["question_id"]


def _navigation_error(error):
    return {"action": "error", **error}


def _default_next_step(questions, index):
    if index + 1 < len(questions):
        return {
            "action": "goto_question",
            "question_id": _question_id(questions[index + 1]),
            "matched_rule_id": None,
        }
    return {"action": "end", "matched_rule_id": None}


def _prepare_questions(questions):
    """Sort and defensively validate the runtime fields required by the algorithms."""
    if not isinstance(questions, Sequence) or isinstance(questions, (str, bytes)):
        return None, _error("invalid_survey_definition", "questions must be a sequence")
    if not questions:
        return None, _error("empty_survey", "survey has no questions")

    question_ids = []
    seen_ids = set()
    for question in questions:
        try:
            question_id = _question_id(question)
            hash(question_id)
        except (TypeError, ValueError):
            return None, _error(
                "missing_question_id",
                "question definition must contain a hashable question_id",
            )
        if question_id is None:
            return None, _error("missing_question_id", "question_id cannot be null")
        if question_id in seen_ids:
            return None, _error(
                "duplicate_question_id",
                "question IDs must be unique",
                question_id,
            )
        seen_ids.add(question_id)
        question_ids.append(question_id)

    seen_orders = set()
    for question, question_id in zip(questions, question_ids):
        order = question.get("order")
        if not _is_finite_number(order):
            return None, _error(
                "invalid_question_order",
                "question order must be a finite number",
                question_id,
            )
        if order in seen_orders:
            return None, _error(
                "duplicate_question_order",
                "question order values must be unique",
                question_id,
            )
        seen_orders.add(order)

        validation = question.get("validation", {})
        if validation is not None and not isinstance(validation, Mapping):
            return None, _error(
                "invalid_survey_definition",
                "question validation must be an object",
                question_id,
            )
        validation = validation or {}
        question_type = question.get("type")
        if not isinstance(question_type, str):
            question_type = None
        if question_type not in {
            "single_choice",
            "multiple_choice",
            "number_input",
            "text_input",
        }:
            return None, _error(
                "invalid_survey_definition",
                "question type is missing or unsupported",
                question_id,
            )
        if "required" in question and not isinstance(question["required"], bool):
            return None, _error(
                "invalid_survey_definition",
                "question required flag must be a boolean",
                question_id,
            )

        if question_type == "multiple_choice":
            counts = [
                validation.get("exact_selected"),
                validation.get("min_selected"),
                validation.get("max_selected"),
            ]
            if any(
                value is not None
                and (not isinstance(value, int) or isinstance(value, bool) or value < 0)
                for value in counts
            ):
                return None, _error(
                    "invalid_survey_definition",
                    "multiple-choice selection constraints must be non-negative integers",
                    question_id,
                )
            minimum = validation.get("min_selected")
            maximum = validation.get("max_selected")
            if minimum is not None and maximum is not None and minimum > maximum:
                return None, _error(
                    "invalid_survey_definition",
                    "minimum selections cannot exceed maximum selections",
                    question_id,
                )
        elif question_type == "number_input":
            minimum = validation.get("min_value")
            maximum = validation.get("max_value")
            if any(
                value is not None and not _is_finite_number(value)
                for value in (minimum, maximum)
            ):
                return None, _error(
                    "invalid_survey_definition",
                    "numeric answer constraints must be finite numbers",
                    question_id,
                )
            if minimum is not None and maximum is not None and minimum > maximum:
                return None, _error(
                    "invalid_survey_definition",
                    "numeric minimum cannot exceed numeric maximum",
                    question_id,
                )
            if "integer_only" in validation and not isinstance(
                validation["integer_only"], bool
            ):
                return None, _error(
                    "invalid_survey_definition",
                    "integer_only must be a boolean",
                    question_id,
                )
        elif question_type == "text_input":
            minimum = validation.get("min_length")
            maximum = validation.get("max_length")
            if any(
                value is not None
                and (not isinstance(value, int) or isinstance(value, bool) or value < 0)
                for value in (minimum, maximum)
            ):
                return None, _error(
                    "invalid_survey_definition",
                    "text length constraints must be non-negative integers",
                    question_id,
                )
            if minimum is not None and maximum is not None and minimum > maximum:
                return None, _error(
                    "invalid_survey_definition",
                    "minimum text length cannot exceed maximum text length",
                    question_id,
                )

        is_choice_question = question_type in {"single_choice", "multiple_choice"}
        if is_choice_question:
            if "options" not in question:
                return None, _error(
                    "invalid_survey_definition",
                    "choice question must define an options array",
                    question_id,
                )
            options = question.get("options", [])
            if not isinstance(options, Sequence) or isinstance(options, (str, bytes)):
                return None, _error(
                    "invalid_survey_definition",
                    "choice question options must be a sequence",
                    question_id,
                )
            seen_options = set()
            for option in options:
                option_id = option.get("option_id") if isinstance(option, Mapping) else None
                try:
                    hash(option_id)
                except TypeError:
                    option_id = None
                if option_id is None:
                    return None, _error(
                        "missing_option_id",
                        "each choice option must contain a hashable option_id",
                        question_id,
                    )
                if option_id in seen_options:
                    return None, _error(
                        "duplicate_option_id",
                        "option IDs must be unique within a question",
                        question_id,
                    )
                seen_options.add(option_id)

    question_map = dict(zip(question_ids, questions))
    supported_operators = {
        "single_choice": {"equals", "not_equals", "in"},
        "multiple_choice": {
            "contains_any",
            "contains_all",
            "equals_set",
            "selected_count_eq",
            "selected_count_gte",
            "selected_count_lte",
        },
        "number_input": {"lt", "lte", "gt", "gte", "equals", "between"},
    }

    for question, question_id in zip(questions, question_ids):
        if "jump_rules" not in question:
            continue
        rules = question["jump_rules"]
        if not isinstance(rules, Sequence) or isinstance(rules, (str, bytes)):
            return None, _error(
                "invalid_survey_definition",
                "jump_rules must be a sequence when provided",
                question_id,
            )

        seen_priorities = set()
        question_type = question.get("type")
        if not isinstance(question_type, str):
            question_type = None
        option_ids = (
            set(_option_ids(question))
            if question_type in {"single_choice", "multiple_choice"}
            else set()
        )
        for rule in rules:
            if not isinstance(rule, Mapping):
                return None, _error(
                    "invalid_survey_definition",
                    "each jump rule must be an object",
                    question_id,
                )
            if "rule_id" not in rule or rule["rule_id"] is None:
                return None, _error(
                    "invalid_survey_definition",
                    "jump rule must define a rule_id",
                    question_id,
                )
            priority = rule.get("priority")
            if not _is_finite_number(priority):
                return None, _error(
                    "invalid_rule_priority",
                    "jump rule priority must be a finite number",
                    question_id,
                )
            if priority in seen_priorities:
                return None, _error(
                    "duplicate_rule_priority",
                    "jump rule priorities must be unique within a question",
                    question_id,
                )
            seen_priorities.add(priority)

            target = rule.get("target")
            if not isinstance(target, Mapping):
                return None, _error(
                    "invalid_target_type",
                    "jump rule target must be an object with a supported type",
                    question_id,
                )
            if target.get("type") == "question":
                target_id = target.get("question_id")
                try:
                    target_exists = target_id in question_map
                except TypeError:
                    target_exists = False
                if not target_exists:
                    return None, _error(
                        "invalid_runtime_target",
                        "jump rule targets an unknown question",
                        target_id if target_id is not None else question_id,
                    )
            elif target.get("type") != "end":
                return None, _error(
                    "invalid_target_type",
                    "jump target type must be 'question' or 'end'",
                    question_id,
                )

            condition = rule.get("condition")
            operator = condition.get("operator") if isinstance(condition, Mapping) else None
            if not isinstance(operator, str) or operator not in supported_operators.get(
                question_type, set()
            ):
                return None, _error(
                    "unsupported_operator_for_question_type",
                    "jump rule operator is not supported for this question type",
                    question_id,
                )

            if question_type == "single_choice":
                if operator in {"equals", "not_equals"}:
                    values = [condition.get("value")]
                else:
                    values = condition.get("values")
                    if not isinstance(values, list) or not values:
                        return None, _error(
                            "empty_condition_values",
                            "in condition values must be a non-empty array",
                            question_id,
                        )
                try:
                    has_unknown_value = any(value not in option_ids for value in values)
                except TypeError:
                    has_unknown_value = True
                if has_unknown_value:
                    return None, _error(
                        "invalid_condition_option",
                        "jump condition references an unknown option_id",
                        question_id,
                    )
            elif question_type == "multiple_choice":
                if operator in {"contains_any", "contains_all", "equals_set"}:
                    values = condition.get("values")
                    if not isinstance(values, list) or not values:
                        return None, _error(
                            "empty_condition_values",
                            "set condition values must be a non-empty array",
                            question_id,
                        )
                    try:
                        unique_values = set(values)
                    except TypeError:
                        unique_values = set()
                    if len(unique_values) != len(values) or any(
                        value not in option_ids for value in values
                    ):
                        return None, _error(
                            "invalid_condition_option",
                            "set condition values must be unique defined option IDs",
                            question_id,
                        )
                else:
                    count = condition.get("value")
                    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                        return None, _error(
                            "invalid_count_condition",
                            "count condition value must be a non-negative integer",
                            question_id,
                        )
            elif question_type == "number_input":
                boundaries = (
                    (condition.get("min"), condition.get("max"))
                    if operator == "between"
                    else (condition.get("value"),)
                )
                if any(not _is_finite_number(boundary) for boundary in boundaries):
                    return None, _error(
                        "invalid_numeric_boundary",
                        "numeric jump conditions require finite numeric boundaries",
                        question_id,
                    )
                if operator == "between" and boundaries[0] > boundaries[1]:
                    return None, _error(
                        "invalid_numeric_range",
                        "between condition minimum cannot exceed its maximum",
                        question_id,
                    )

    try:
        ordered_questions = sorted(questions, key=lambda question: question["order"])
    except (KeyError, TypeError, ValueError, OverflowError):
        return None, _error("invalid_question_order", "question orders cannot be sorted")
    return ordered_questions, None


def resolve_next_step(questions, question_id, answers):
    """Return the documented navigation action for the current question."""
    if not isinstance(answers, Mapping):
        return _navigation_error(
            _error("invalid_answer", "answers must be a mapping", question_id)
        )

    ordered_questions, definition_error = _prepare_questions(questions)
    if definition_error is not None:
        return _navigation_error(definition_error)

    current_question = None
    current_index = -1
    for index, question in enumerate(ordered_questions):
        if _question_id(question) == question_id:
            current_index = index
            current_question = question
            break

    if current_question is None:
        return _navigation_error(
            _error(
                "unknown_current_question",
                f"question not found: {question_id}",
                question_id,
            )
        )

    # Presence of the key is intentional: a submitted but invalid value is not missing.
    if question_id not in answers:
        return {
            "action": "awaiting_answer",
            "question_id": question_id,
            "matched_rule_id": None,
        }

    answer_error = _validate_answer(current_question, answers[question_id])
    if answer_error is not None:
        return _navigation_error(answer_error)
    answer_value = answers[question_id]["value"]

    sorted_rules = sorted(
        current_question.get("jump_rules", []),
        key=lambda rule: rule["priority"],
    )
    for rule in sorted_rules:
        if condition_matches(current_question.get("type"), rule["condition"], answer_value):
            target = rule["target"]
            if target["type"] == "end":
                return {
                    "action": "end",
                    "matched_rule_id": rule.get("rule_id"),
                }
            return {
                "action": "goto_question",
                "question_id": target["question_id"],
                "matched_rule_id": rule.get("rule_id"),
            }

    return _default_next_step(ordered_questions, current_index)


def _error(code, message, question_id=None):
    error = {"code": code, "message": message}
    if question_id is not None:
        error["question_id"] = question_id
    return error


def _result(path, error=None, skipped_required_questions=None):
    result = {
        "valid": error is None,
        "path": path,
        "errors": [] if error is None else [error],
    }
    if error is None:
        result["skipped_required_questions"] = skipped_required_questions or []
    return result


def _option_ids(question):
    return [option["option_id"] for option in question.get("options", [])]


def _is_integer_number(value):
    if isinstance(value, Integral):
        return True
    if isinstance(value, Fraction):
        return value.denominator == 1
    if not isinstance(value, Real):
        return False
    try:
        return value.is_integer()
    except (AttributeError, OverflowError, TypeError, ValueError):
        return False


def validate_submission(questions, answers, max_jump_steps=None):
    """Validate a submission against the server-computed questionnaire path.

    ``questions`` is sorted by the documented ``order`` field. ``answers`` is a
    mapping keyed by question ID with documented answer objects. The function
    performs no HTTP or database access.
    """
    if not isinstance(answers, Mapping):
        return _result([], _error("invalid_answer", "answers must be a mapping"))

    ordered_questions, definition_error = _prepare_questions(questions)
    if definition_error is not None:
        return _result([], definition_error)

    question_ids = [_question_id(question) for question in ordered_questions]

    question_map = dict(zip(question_ids, ordered_questions))
    for submitted_question_id in answers:
        if submitted_question_id not in question_map:
            return _result(
                [],
                _error(
                    "unknown_answer_question",
                    "submitted answer references an unknown question",
                    submitted_question_id,
                ),
            )

    rule_count = sum(len(question.get("jump_rules", [])) for question in ordered_questions)
    if max_jump_steps is None:
        step_limit = max(len(ordered_questions) + 1, len(ordered_questions) + rule_count + 1)
    else:
        if (
            not isinstance(max_jump_steps, int)
            or isinstance(max_jump_steps, bool)
            or max_jump_steps <= 0
        ):
            return _result(
                [],
                _error(
                    "invalid_max_jump_steps",
                    "max_jump_steps must be a positive integer",
                ),
            )
        step_limit = max_jump_steps

    path = []
    visited = set()
    current_question_id = question_ids[0]
    steps = 0

    while current_question_id is not None:
        if current_question_id not in question_map:
            return _result(
                path,
                _error(
                    "invalid_runtime_target",
                    "jump rule targets an unknown question",
                    current_question_id,
                ),
            )
        if current_question_id in visited:
            return _result(
                path,
                _error(
                    "jump_cycle_detected",
                    "jump traversal revisited a question",
                    current_question_id,
                ),
            )

        steps += 1
        if steps > step_limit:
            return _result(
                path,
                _error(
                    "max_jump_steps_exceeded",
                    "jump traversal exceeded the configured safety limit",
                ),
            )

        visited.add(current_question_id)
        path.append(current_question_id)
        current_question = question_map[current_question_id]

        if current_question_id not in answers:
            if current_question.get("required", False):
                return _result(
                    path,
                    _error(
                        "missing_required_answer",
                        "required question on the answer path has no submitted answer",
                        current_question_id,
                    ),
                )
            next_step = _default_next_step(
                ordered_questions,
                question_ids.index(current_question_id),
            )
        else:
            answer_error = _validate_answer(current_question, answers[current_question_id])
            if answer_error is not None:
                return _result(path, answer_error)
            next_step = resolve_next_step(
                ordered_questions,
                current_question_id,
                answers,
            )

        if next_step.get("action") == "error":
            code = next_step.get("code", "invalid_navigation_result")
            return _result(
                path,
                _error(
                    code if code == "invalid_runtime_target" else "invalid_navigation_result",
                    next_step.get("message", "navigation returned an error"),
                    next_step.get("question_id", current_question_id),
                ),
            )
        if next_step.get("action") == "end":
            current_question_id = None
        elif next_step.get("action") == "goto_question":
            current_question_id = next_step.get("question_id")
        else:
            return _result(
                path,
                _error(
                    "invalid_navigation_result",
                    "navigation returned an unsupported result",
                    current_question_id,
                ),
            )

    for submitted_question_id in answers:
        if submitted_question_id not in visited:
            return _result(
                path,
                _error(
                    "answer_not_on_path",
                    "submitted answer is not on the server-computed answer path",
                    submitted_question_id,
                ),
            )

    skipped_required = [
        question_id
        for question_id, question in zip(question_ids, ordered_questions)
        if question.get("required", False) and question_id not in visited
    ]
    return _result(path, skipped_required_questions=skipped_required)
