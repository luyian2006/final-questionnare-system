"""Question library, immutable versions, usage, and aggregate statistics."""

from copy import deepcopy
import secrets

from bson import ObjectId
from pymongo.errors import DuplicateKeyError

from app.algorithms.answer_validator import validate_answer
from app.algorithms.survey_validator import validate_survey_definition
from app.services import normalize_questions, now, update_survey


class QuestionAccessError(PermissionError):
    pass


class QuestionDefinitionError(ValueError):
    def __init__(self, errors):
        super().__init__("question definition is invalid")
        self.errors = errors


def _object_id(value):
    if not ObjectId.is_valid(value):
        return None
    return ObjectId(value)


def _prepare_content(content, default_question_id):
    if not isinstance(content, dict):
        raise ValueError("content must be an object")
    prepared = deepcopy(content)
    prepared.pop("source_question_item_id", None)
    prepared.pop("source_question_version_id", None)
    prepared["question_id"] = prepared.get("question_id") or default_question_id
    prepared["order"] = 1
    prepared = normalize_questions([prepared])[0]

    # Validate the existing question shape and rule conditions while allowing a
    # library question to reference targets that will only exist in a survey.
    validation_copy = deepcopy(prepared)
    for rule in validation_copy.get("jump_rules", []):
        if not isinstance(rule, dict):
            continue
        target = rule.get("target")
        if not isinstance(target, dict) or target.get("type") not in {"question", "end"}:
            continue
        if target.get("type") == "question" and not isinstance(target.get("question_id"), str):
            continue
        rule["target"] = {"type": "end"}
    result = validate_survey_definition([validation_copy])
    if not result["valid"]:
        raise QuestionDefinitionError(result["errors"])
    return prepared


def _version_view(version):
    return {
        "version_id": str(version["_id"]),
        "question_item_id": str(version["question_item_id"]),
        "version_number": version["version_number"],
        "content": version["content"],
        "created_by_user_id": str(version["created_by_user_id"]),
        "created_at": version["created_at"],
        "based_on_version_id": str(version["based_on_version_id"]) if version.get("based_on_version_id") else None,
        "restored_from_version_id": str(version["restored_from_version_id"]) if version.get("restored_from_version_id") else None,
    }


def _item_view(item, version=None):
    result = {
        "question_item_id": str(item["_id"]),
        "owner_user_id": str(item["owner_user_id"]),
        "display_title": item["display_title"],
        "is_shared": item.get("is_shared", False),
        "current_version_id": str(item["current_version_id"]) if item.get("current_version_id") else None,
        "latest_version_number": item.get("latest_version_number", 0),
        "derived_from_item_id": str(item["derived_from_item_id"]) if item.get("derived_from_item_id") else None,
        "derived_from_version_id": str(item["derived_from_version_id"]) if item.get("derived_from_version_id") else None,
        "created_at": item["created_at"],
        "updated_at": item["updated_at"],
    }
    if version is not None:
        result["current_version"] = _version_view(version)
    return result


def _find_item(database, item_id):
    oid = _object_id(item_id)
    return None if oid is None else database.question_items.find_one({"_id": oid})


def accessible_item(database, user_id, item_id):
    item = _find_item(database, item_id)
    if item is None or (item["owner_user_id"] != user_id and not item.get("is_shared", False)):
        return None
    return item


def owner_item(database, user_id, item_id):
    item = _find_item(database, item_id)
    if item is None or item["owner_user_id"] != user_id:
        return None
    return item


def _find_version(database, item, version_id):
    oid = _object_id(version_id)
    if oid is None:
        return None
    return database.question_versions.find_one({"_id": oid, "question_item_id": item["_id"]})


def _insert_version(database, item, user_id, content, based_on=None, restored_from=None):
    number = item.get("latest_version_number", 0) + 1
    prepared = _prepare_content(content, f"library_{item['_id']}")
    version = {
        "question_item_id": item["_id"],
        "version_number": number,
        "content": prepared,
        "created_by_user_id": user_id,
        "created_at": now(),
        "based_on_version_id": based_on,
        "restored_from_version_id": restored_from,
    }
    try:
        inserted = database.question_versions.insert_one(version)
    except DuplicateKeyError as exc:
        raise ValueError("question version conflict; reload and retry") from exc
    version["_id"] = inserted.inserted_id
    timestamp = now()
    database.question_items.update_one(
        {"_id": item["_id"], "owner_user_id": user_id},
        {"$set": {"current_version_id": version["_id"], "latest_version_number": number, "updated_at": timestamp}},
    )
    item.update({"current_version_id": version["_id"], "latest_version_number": number, "updated_at": timestamp})
    return version


def create_question_item(database, user_id, data, derived_from_item_id=None, derived_from_version_id=None):
    content = data.get("content") if isinstance(data, dict) else None
    title = data.get("display_title") or (content.get("title") if isinstance(content, dict) else None)
    if not isinstance(title, str) or not title.strip():
        raise ValueError("display_title is required")
    _prepare_content(content or {}, "library_pending")
    timestamp = now()
    item = {
        "owner_user_id": user_id,
        "display_title": title.strip(),
        "is_shared": bool(data.get("is_shared", False)),
        "current_version_id": None,
        "latest_version_number": 0,
        "derived_from_item_id": derived_from_item_id,
        "derived_from_version_id": derived_from_version_id,
        "created_at": timestamp,
        "updated_at": timestamp,
    }
    inserted = database.question_items.insert_one(item)
    item["_id"] = inserted.inserted_id
    version = _insert_version(database, item, user_id, content or {})
    return _item_view(item, version)


def list_question_items(database, user_id, scope="all"):
    if scope not in {"all", "mine", "shared"}:
        raise ValueError("scope must be all, mine, or shared")
    items = []
    if scope in {"all", "mine"}:
        items.extend(database.question_items.find({"owner_user_id": user_id}))
    if scope in {"all", "shared"}:
        items.extend(
            item for item in database.question_items.find({"is_shared": True})
            if item["owner_user_id"] != user_id
        )
    unique = {item["_id"]: item for item in items}
    output = []
    for item in sorted(unique.values(), key=lambda value: value.get("updated_at"), reverse=True):
        version = database.question_versions.find_one({"_id": item.get("current_version_id")})
        output.append(_item_view(item, version))
    return output


def get_question_item(database, user_id, item_id):
    item = accessible_item(database, user_id, item_id)
    if item is None:
        return None
    version = database.question_versions.find_one({"_id": item.get("current_version_id")})
    return _item_view(item, version)


def update_question_item(database, user_id, item_id, data):
    item = owner_item(database, user_id, item_id)
    if item is None:
        return None
    changes = {"updated_at": now()}
    if "display_title" in data:
        if not isinstance(data["display_title"], str) or not data["display_title"].strip():
            raise ValueError("display_title is required")
        changes["display_title"] = data["display_title"].strip()
    if "is_shared" in data:
        changes["is_shared"] = bool(data["is_shared"])
    database.question_items.update_one({"_id": item["_id"], "owner_user_id": user_id}, {"$set": changes})
    item.update(changes)
    version = database.question_versions.find_one({"_id": item.get("current_version_id")})
    return _item_view(item, version)


def list_versions(database, user_id, item_id):
    item = accessible_item(database, user_id, item_id)
    if item is None:
        return None
    versions = list(database.question_versions.find({"question_item_id": item["_id"]}))
    versions.sort(key=lambda value: value["version_number"], reverse=True)
    return [_version_view(version) for version in versions]


def get_version(database, user_id, item_id, version_id):
    item = accessible_item(database, user_id, item_id)
    if item is None:
        return None
    version = _find_version(database, item, version_id)
    return None if version is None else _version_view(version)


def create_version(database, user_id, item_id, data):
    item = owner_item(database, user_id, item_id)
    if item is None:
        return None
    based_on = _find_version(database, item, data.get("based_on_version_id")) if data.get("based_on_version_id") else None
    if data.get("based_on_version_id") and based_on is None:
        raise ValueError("based_on_version_id is not a version of this question")
    version = _insert_version(
        database,
        item,
        user_id,
        data.get("content", {}),
        based_on=based_on["_id"] if based_on else item.get("current_version_id"),
    )
    return _version_view(version)


def restore_version(database, user_id, item_id, version_id):
    item = owner_item(database, user_id, item_id)
    if item is None:
        return None
    source = _find_version(database, item, version_id)
    if source is None:
        raise ValueError("version not found")
    version = _insert_version(
        database,
        item,
        user_id,
        source["content"],
        based_on=item.get("current_version_id"),
        restored_from=source["_id"],
    )
    return _version_view(version)


def derive_question(database, user_id, item_id, data):
    source_item = accessible_item(database, user_id, item_id)
    if source_item is None:
        return None
    source = _find_version(database, source_item, data.get("version_id")) if data.get("version_id") else database.question_versions.find_one({"_id": source_item.get("current_version_id")})
    if source is None:
        raise ValueError("version not found")
    return create_question_item(
        database,
        user_id,
        {
            "display_title": data.get("display_title") or f"{source_item['display_title']}（派生）",
            "content": source["content"],
            "is_shared": bool(data.get("is_shared", False)),
        },
        derived_from_item_id=source_item["_id"],
        derived_from_version_id=source["_id"],
    )


def add_version_to_survey(database, user_id, survey, item_id, version_id):
    item = accessible_item(database, user_id, item_id)
    if item is None:
        raise QuestionAccessError("question not found")
    version = _find_version(database, item, version_id)
    if version is None:
        raise QuestionAccessError("question version not found")

    current = next((value for value in survey.get("versions", []) if value["version"] == survey["current_version"]), None)
    if current is None:
        raise ValueError("survey has no current version")
    questions = deepcopy(current.get("questions", []))
    used_ids = {question.get("question_id") for question in questions}
    local_id = f"qlib_{secrets.token_hex(6)}"
    while local_id in used_ids:
        local_id = f"qlib_{secrets.token_hex(6)}"

    copied = deepcopy(version["content"])
    source_local_id = copied.get("question_id")
    copied["question_id"] = local_id
    copied["order"] = max((question.get("order", 0) for question in questions), default=0) + 1
    copied["source_question_item_id"] = str(item["_id"])
    copied["source_question_version_id"] = str(version["_id"])
    for rule in copied.get("jump_rules", []):
        target = rule.get("target", {}) if isinstance(rule, dict) else {}
        if target.get("type") == "question" and target.get("question_id") == source_local_id:
            target["question_id"] = local_id
    questions.append(copied)
    return update_survey(database, survey, {"questions": questions}, trusted_question_sources=True)


def question_usage(database, user_id, item_id):
    item = owner_item(database, user_id, item_id)
    if item is None:
        return None
    usages = []
    item_text = str(item["_id"])
    for survey in database.surveys.find({}):
        for version in survey.get("versions", []):
            for question in version.get("questions", []):
                if question.get("source_question_item_id") == item_text:
                    usages.append({
                        "survey_id": str(survey["_id"]),
                        "survey_title": survey.get("title", ""),
                        "survey_version": version["version"],
                        "survey_version_state": version.get("state"),
                        "local_question_id": question.get("question_id"),
                        "source_question_version_id": question.get("source_question_version_id"),
                    })
    return {"question_item_id": item_text, "usages": usages, "usage_count": len(usages)}


def cross_survey_statistics(database, user_id, item_id, version_id):
    item = owner_item(database, user_id, item_id)
    if item is None:
        return None
    version = _find_version(database, item, version_id)
    if version is None:
        raise ValueError("version not found")
    source_id = str(version["_id"])
    definition = version["content"]
    values = []
    response_ids = set()
    survey_ids = set()
    for response in database.responses.find({"status": "submitted"}):
        questions = response.get("survey_snapshot", {}).get("questions", [])
        for question in questions:
            if question.get("source_question_version_id") != source_id:
                continue
            local_id = question.get("question_id")
            answer = next((candidate for candidate in response.get("answers", []) if candidate.get("question_id") == local_id), None)
            if answer is None or validate_answer(question, answer) is not None:
                continue
            value = answer.get("value")
            if value == "" or value == []:
                continue
            values.append(value)
            response_ids.add(str(response["_id"]))
            survey_ids.add(str(response["survey_id"]))

    question_type = definition.get("type")
    result = {
        "question_item_id": str(item["_id"]),
        "question_version_id": source_id,
        "version_number": version["version_number"],
        "type": question_type,
        "valid_answer_count": len(values),
        "response_count": len(response_ids),
        "survey_count": len(survey_ids),
    }
    if question_type in {"single_choice", "multiple_choice"}:
        counts = {option.get("option_id"): 0 for option in definition.get("options", [])}
        for value in values:
            selected = value if question_type == "multiple_choice" else [value]
            for option_id in selected:
                if option_id in counts:
                    counts[option_id] += 1
        denominator = len(values)
        result["denominator"] = "valid_answer_count"
        result["options"] = [
            {
                "option_id": option.get("option_id"),
                "label": option.get("label", ""),
                "count": counts.get(option.get("option_id"), 0),
                "ratio": counts.get(option.get("option_id"), 0) / denominator if denominator else 0,
            }
            for option in definition.get("options", [])
        ]
    elif question_type == "number_input":
        result.update({
            "average": sum(values) / len(values) if values else None,
            "minimum": min(values) if values else None,
            "maximum": max(values) if values else None,
        })
    elif question_type == "text_input":
        result["text_answer_count"] = len(values)
    return result
