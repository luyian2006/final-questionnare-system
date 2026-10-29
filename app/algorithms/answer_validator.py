"""Type-specific validation for submitted answer objects."""

import math
from collections.abc import Mapping
from fractions import Fraction
from numbers import Integral, Real


MISSING = object()


def _error(code, message, question_id=None):
    error = {"code": code, "message": message}
    if question_id is not None:
        error["question_id"] = question_id
    return error


def _finite_number(value):
    if not isinstance(value, Real) or isinstance(value, bool):
        return False
    if isinstance(value, (Integral, Fraction)):
        return True
    try:
        return math.isfinite(value)
    except (OverflowError, TypeError, ValueError):
        return False


def _integer_number(value):
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


def validate_answer(question, answer=MISSING):
    """Return a documented error object, or ``None`` when the answer is valid.

    The caller handles absent optional answers as traversal behavior; passing
    ``MISSING`` here still distinguishes absence from a submitted ``None``.
    """
    question_id = question.get("question_id") if isinstance(question, Mapping) else None
    question_type = question.get("type") if isinstance(question, Mapping) else None
    if answer is MISSING:
        if isinstance(question, Mapping) and question.get("required", False):
            return _error("missing_required_answer", "required answer is missing", question_id)
        return None
    if not isinstance(question, Mapping):
        return _error("invalid_survey_definition", "question must be an object")
    if not isinstance(answer, Mapping):
        return _error(
            "invalid_answer",
            "answer must be an object containing question_id, type, and value",
            question_id,
        )
    if "question_id" not in answer:
        return _error("invalid_answer", "answer is missing its question_id", question_id)
    if answer["question_id"] != question_id:
        return _error("invalid_answer", "answer question_id does not match the submitted question", question_id)
    if "type" not in answer or answer["type"] != question_type:
        return _error("invalid_answer_type", "answer type is missing or does not match the question type", question_id)
    if "value" not in answer:
        return _error("invalid_answer", "answer is missing its value", question_id)
    value = answer["value"]
    validation = question.get("validation") or {}
    if not isinstance(validation, Mapping):
        return _error("invalid_survey_definition", "validation must be an object", question_id)

    if question_type == "single_choice":
        if value is None or isinstance(value, (Mapping, list, tuple, set)):
            return _error("invalid_answer", "single-choice answer must be a scalar value", question_id)
        try:
            hash(value)
            options = [option["option_id"] for option in question.get("options", [])]
            is_valid = value in options
        except (KeyError, TypeError):
            is_valid = False
        if not is_valid:
            return _error("invalid_answer_option", "single-choice answer must reference a defined option_id", question_id)
        return None

    if question_type == "multiple_choice":
        if not isinstance(value, list):
            return _error("invalid_answer", "multiple-choice answer must be a list", question_id)
        try:
            unique_values = set(value)
        except TypeError:
            return _error("invalid_answer", "multiple-choice options must be scalar values", question_id)
        if len(unique_values) != len(value):
            return _error("duplicate_answer_option", "multiple-choice answer contains duplicate option IDs", question_id)
        if question.get("required") and not value:
            return _error("invalid_answer", "required multiple-choice answer must select at least one option", question_id)
        try:
            options = {option["option_id"] for option in question.get("options", [])}
            if any(item not in options for item in value):
                return _error("invalid_answer_option", "multiple-choice answer contains an unknown option_id", question_id)
        except (KeyError, TypeError):
            return _error("invalid_answer_option", "multiple-choice answer contains an unknown option_id", question_id)
        count = len(value)
        exact = validation.get("exact_selected")
        minimum = validation.get("min_selected")
        maximum = validation.get("max_selected")
        if exact is not None and count != exact:
            return _error("invalid_answer", "multiple-choice answer has an invalid selection count", question_id)
        if exact is None and minimum is not None and count < minimum:
            return _error("invalid_answer", "multiple-choice answer selects too few options", question_id)
        if exact is None and maximum is not None and count > maximum:
            return _error("invalid_answer", "multiple-choice answer selects too many options", question_id)
        return None

    if question_type == "text_input":
        if not isinstance(value, str):
            return _error("invalid_answer", "text answer must be a string", question_id)
        if question.get("required") and value == "":
            return _error("invalid_answer", "required text answer must not be empty", question_id)
        minimum = validation.get("min_length")
        maximum = validation.get("max_length")
        if any(item is not None and (not isinstance(item, int) or isinstance(item, bool) or item < 0) for item in (minimum, maximum)):
            return _error("invalid_survey_definition", "text length constraints must be non-negative integers", question_id)
        if minimum is not None and maximum is not None and minimum > maximum:
            return _error("invalid_survey_definition", "minimum text length exceeds maximum", question_id)
        if minimum is not None and len(value) < minimum:
            return _error("invalid_answer", "text answer is shorter than the minimum length", question_id)
        if maximum is not None and len(value) > maximum:
            return _error("invalid_answer", "text answer exceeds the maximum length", question_id)
        return None

    if question_type == "number_input":
        if isinstance(value, Real) and not isinstance(value, bool) and not _finite_number(value):
            return _error("number_not_finite", "number answer must be finite", question_id)
        if not isinstance(value, Real) or isinstance(value, bool):
            return _error("invalid_answer", "number answer must be numeric", question_id)
        minimum = validation.get("min_value")
        maximum = validation.get("max_value")
        if any(item is not None and not _finite_number(item) for item in (minimum, maximum)):
            return _error("invalid_survey_definition", "numeric answer constraints must be finite", question_id)
        if minimum is not None and maximum is not None and minimum > maximum:
            return _error("invalid_survey_definition", "numeric minimum exceeds maximum", question_id)
        if minimum is not None and value < minimum:
            return _error("invalid_answer", "number is below the minimum value", question_id)
        if maximum is not None and value > maximum:
            return _error("invalid_answer", "number is above the maximum value", question_id)
        if validation.get("integer_only") and not _integer_number(value):
            return _error("invalid_answer", "number must be an integer", question_id)
        return None

    return _error("invalid_answer", f"unsupported question type: {question_type!r}", question_id)
