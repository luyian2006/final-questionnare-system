"""Publishing-time validation for questionnaire definitions."""

from collections.abc import Mapping, Sequence
import math
from fractions import Fraction
from numbers import Integral, Real


def _is_finite_number(value):
    if not isinstance(value, Real) or isinstance(value, bool):
        return False
    if isinstance(value, (Integral, Fraction)):
        return True
    try:
        return math.isfinite(value)
    except (OverflowError, TypeError, ValueError):
        return False


QUESTION_TYPES = {"single_choice", "multiple_choice", "text_input", "number_input"}
OPERATORS = {
    "single_choice": {"equals", "not_equals", "in"},
    "multiple_choice": {
        "contains_any", "contains_all", "equals_set", "selected_count_eq",
        "selected_count_gte", "selected_count_lte",
    },
    "number_input": {"lt", "lte", "gt", "gte", "equals", "between"},
}


def _error(code, message, question_id=None, rule_id=None):
    error = {"code": code, "message": message}
    if question_id is not None:
        error["question_id"] = question_id
    if rule_id is not None:
        error["rule_id"] = rule_id
    return error


def _invalid(code, message, question_id=None, rule_id=None):
    return {"valid": False, "errors": [_error(code, message, question_id, rule_id)]}


def _sequence(value):
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes))


def validate_survey_definition(questions):
    """Validate a publishable question list and return stable structured errors."""
    if not _sequence(questions):
        return _invalid("invalid_survey_definition", "questions must be an array")
    if not questions:
        return _invalid("empty_survey", "survey has no questions")

    seen_ids = set()
    seen_orders = set()
    for question in questions:
        if not isinstance(question, Mapping):
            return _invalid("invalid_survey_definition", "each question must be an object")
        question_id = question.get("question_id")
        if not isinstance(question_id, str) or not question_id.strip():
            return _invalid("missing_question_id", "question_id must be a non-empty string")
        if question_id in seen_ids:
            return _invalid("duplicate_question_id", "question IDs must be unique", question_id)
        seen_ids.add(question_id)
        order = question.get("order")
        if not _is_finite_number(order):
            return _invalid("invalid_question_order", "question order must be finite numeric", question_id)
        if order in seen_orders:
            return _invalid("duplicate_question_order", "question order values must be unique", question_id)
        seen_orders.add(order)
        question_type = question.get("type")
        if not isinstance(question_type, str) or question_type not in QUESTION_TYPES:
            return _invalid("invalid_survey_definition", "question type is missing or unsupported", question_id)
        if not isinstance(question.get("title"), str):
            return _invalid("invalid_survey_definition", "question title must be a string", question_id)
        if not isinstance(question.get("required"), bool):
            return _invalid("invalid_survey_definition", "required must be a boolean", question_id)
        validation = question.get("validation", {})
        if not isinstance(validation, Mapping):
            return _invalid("invalid_survey_definition", "validation must be an object", question_id)

        if question_type in {"single_choice", "multiple_choice"}:
            options = question.get("options")
            if not _sequence(options):
                return _invalid("invalid_survey_definition", "choice question options must be an array", question_id)
            option_ids = set()
            for option in options:
                option_id = option.get("option_id") if isinstance(option, Mapping) else None
                if not isinstance(option_id, str) or not option_id:
                    return _invalid("missing_option_id", "each option needs a non-empty option_id", question_id)
                if option_id in option_ids:
                    return _invalid("duplicate_option_id", "option IDs must be unique", question_id)
                option_ids.add(option_id)
                if not isinstance(option.get("label"), str) or not _is_finite_number(option.get("order")):
                    return _invalid("invalid_survey_definition", "options need string labels and numeric order", question_id)
        else:
            option_ids = set()

        if question_type == "multiple_choice":
            for field in ("min_selected", "max_selected", "exact_selected"):
                value = validation.get(field)
                if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
                    return _invalid("invalid_survey_definition", f"{field} must be a non-negative integer", question_id)
            minimum, maximum = validation.get("min_selected"), validation.get("max_selected")
            if minimum is not None and maximum is not None and minimum > maximum:
                return _invalid("invalid_survey_definition", "min_selected cannot exceed max_selected", question_id)
        elif question_type == "text_input":
            for field in ("min_length", "max_length"):
                value = validation.get(field)
                if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 0):
                    return _invalid("invalid_survey_definition", f"{field} must be a non-negative integer", question_id)
            minimum, maximum = validation.get("min_length"), validation.get("max_length")
            if minimum is not None and maximum is not None and minimum > maximum:
                return _invalid("invalid_survey_definition", "min_length cannot exceed max_length", question_id)
        elif question_type == "number_input":
            for field in ("min_value", "max_value"):
                value = validation.get(field)
                if value is not None and not _is_finite_number(value):
                    return _invalid("invalid_survey_definition", f"{field} must be finite numeric", question_id)
            minimum, maximum = validation.get("min_value"), validation.get("max_value")
            if minimum is not None and maximum is not None and minimum > maximum:
                return _invalid("invalid_survey_definition", "min_value cannot exceed max_value", question_id)
            if "integer_only" in validation and not isinstance(validation["integer_only"], bool):
                return _invalid("invalid_survey_definition", "integer_only must be a boolean", question_id)

    question_map = {question["question_id"]: question for question in questions}
    normalized_rules = {}
    for question in questions:
        question_id = question["question_id"]
        option_ids = {
            option["option_id"] for option in question.get("options", [])
        }
        rules = question.get("jump_rules", [])
        if not _sequence(rules):
            return _invalid("invalid_survey_definition", "jump_rules must be an array", question_id)
        priorities = set()
        normalized_rules[question_id] = []
        for rule in rules:
            if not isinstance(rule, Mapping):
                return _invalid("invalid_survey_definition", "each jump rule must be an object", question_id)
            rule_id = rule.get("rule_id")
            priority = rule.get("priority")
            if rule_id is None or not _is_finite_number(priority):
                return _invalid("invalid_rule_priority", "jump rule needs rule_id and finite numeric priority", question_id, rule_id)
            if priority in priorities:
                return _invalid("duplicate_rule_priority", "rule priorities must be unique per question", question_id, rule_id)
            priorities.add(priority)
            target = rule.get("target")
            if not isinstance(target, Mapping):
                return _invalid("invalid_target_type", "jump target must be an object", question_id, rule_id)
            if target.get("type") == "question":
                target_id = target.get("question_id")
                try:
                    target_exists = target_id in question_map
                except TypeError:
                    target_exists = False
                if not target_exists:
                    return _invalid("invalid_jump_target", "jump target question does not exist", question_id, rule_id)
            elif target.get("type") != "end":
                return _invalid("invalid_target_type", "jump target type must be question or end", question_id, rule_id)

            condition = rule.get("condition")
            if not isinstance(condition, Mapping):
                return _invalid("unsupported_operator_for_question_type", "condition must be an object", question_id, rule_id)
            operator = condition.get("operator")
            question_type = question["type"]
            if not isinstance(operator, str) or operator not in OPERATORS.get(question_type, set()):
                return _invalid("unsupported_operator_for_question_type", "operator is incompatible with question type", question_id, rule_id)
            if question_type == "single_choice":
                values = [condition.get("value")] if operator in {"equals", "not_equals"} else condition.get("values")
                if operator == "in" and (not isinstance(values, list) or not values):
                    return _invalid("empty_condition_values", "in values must be a non-empty array", question_id, rule_id)
                if not isinstance(values, list):
                    values = [None]
                if any(not isinstance(value, str) or value not in option_ids for value in values):
                    return _invalid("invalid_condition_option", "condition references an unknown option_id", question_id, rule_id)
            elif question_type == "multiple_choice":
                if operator in {"contains_any", "contains_all", "equals_set"}:
                    values = condition.get("values")
                    if not isinstance(values, list) or not values:
                        return _invalid("empty_condition_values", "set values must be a non-empty array", question_id, rule_id)
                    try:
                        duplicate_values = len(set(values)) != len(values)
                    except TypeError:
                        duplicate_values = True
                    if duplicate_values or any(not isinstance(value, str) or value not in option_ids for value in values):
                        return _invalid("invalid_condition_option", "set condition has duplicate or unknown option IDs", question_id, rule_id)
                else:
                    count = condition.get("value")
                    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                        return _invalid("invalid_count_condition", "count must be a non-negative integer", question_id, rule_id)
            elif question_type == "number_input":
                boundaries = (condition.get("min"), condition.get("max")) if operator == "between" else (condition.get("value"),)
                if any(not _is_finite_number(value) for value in boundaries):
                    return _invalid("invalid_numeric_boundary", "numeric conditions need finite boundaries", question_id, rule_id)
                if operator == "between" and boundaries[0] > boundaries[1]:
                    return _invalid("invalid_numeric_range", "between minimum cannot exceed maximum", question_id, rule_id)
            normalized_rules[question_id].append(rule)

    ordered = sorted(questions, key=lambda question: question["order"])
    graph = {question["question_id"]: [] for question in ordered}
    for index, question in enumerate(ordered[:-1]):
        graph[question["question_id"]].append(ordered[index + 1]["question_id"])
    for question in ordered:
        for rule in normalized_rules[question["question_id"]]:
            if rule["target"]["type"] == "question":
                graph[question["question_id"]].append(rule["target"]["question_id"])

    indegree = {question_id: 0 for question_id in graph}
    for targets in graph.values():
        for target in targets:
            indegree[target] += 1
    queue = [question_id for question_id, degree in indegree.items() if degree == 0]
    visited_count = 0
    while queue:
        source = queue.pop()
        visited_count += 1
        for target in graph[source]:
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    if visited_count != len(graph):
        return _invalid("jump_cycle_detected", "jump graph contains a possible cycle")
    return {"valid": True, "errors": []}
