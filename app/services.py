"""Small service helpers used by the HTTP API.

The service layer deliberately keeps MongoDB documents close to the design
document.  Algorithms receive plain question and answer dictionaries only.
"""

from copy import deepcopy
from datetime import datetime, timezone
import secrets
import string

from bson import ObjectId
from pymongo.errors import DuplicateKeyError, PyMongoError

from app.algorithms.jump import resolve_next_step, validate_submission
from app.algorithms.answer_validator import validate_answer
from app.algorithms.survey_validator import validate_survey_definition
from app.core.security import create_access_token, hash_password, verify_password


def now():
    return datetime.now(timezone.utc)


def normalize_username(username):
    if not isinstance(username, str):
        return ""
    return username.strip().lower()


def public_user(user):
    return {"user_id": str(user["_id"]), "username": user["username"], "created_at": user["created_at"]}


def register(database, username, password):
    normalized = normalize_username(username)
    if not normalized or len(normalized) > 100:
        raise ValueError("username must be a non-empty string")
    if not isinstance(password, str) or len(password) < 6:
        raise ValueError("password must contain at least 6 characters")
    if database.users.find_one({"username_normalized": normalized}) is not None:
        raise ValueError("username already exists")
    created = now()
    user = {
        "username": username.strip(),
        "username_normalized": normalized,
        "password_hash": hash_password(password),
        "password_algorithm": "pbkdf2_sha256",
        "created_at": created,
        "updated_at": created,
        "last_login_at": None,
        "status": "active",
    }
    try:
        result = database.users.insert_one(user)
    except DuplicateKeyError as exc:
        raise ValueError("username already exists") from exc
    user["_id"] = result.inserted_id
    return public_user(user)


def login(database, username, password):
    if not isinstance(password, str):
        raise PermissionError("invalid username or password")
    user = database.users.find_one({"username_normalized": normalize_username(username), "status": "active"})
    if user is None or not verify_password(password, user.get("password_hash", "")):
        raise PermissionError("invalid username or password")
    database.users.update_one({"_id": user["_id"]}, {"$set": {"last_login_at": now()}})
    return {"access_token": create_access_token(str(user["_id"])), "token_type": "bearer", "user": public_user(user)}


def _slug():
    alphabet = string.ascii_letters + string.digits
    return "svy_" + "".join(secrets.choice(alphabet) for _ in range(12))


def parse_deadline(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("deadline_at must be an ISO-8601 datetime") from exc
    else:
        raise ValueError("deadline_at must be an ISO-8601 datetime")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _question_defaults(question, index):
    result = deepcopy(question)
    result.setdefault("title", "")
    result.setdefault("description", "")
    result.setdefault("required", False)
    result.setdefault("order", index + 1)
    result.setdefault("validation", {})
    result.setdefault("jump_rules", [])
    if result.get("type") in {"single_choice", "multiple_choice"}:
        result.setdefault("options", [])
        for option_index, option in enumerate(result["options"]):
            option.setdefault("label", option.get("option_id", ""))
            option.setdefault("order", option_index + 1)
    return result


_QUESTION_SOURCE_FIELDS = ("source_question_item_id", "source_question_version_id")


def _without_question_sources(question):
    result = deepcopy(question)
    for field in _QUESTION_SOURCE_FIELDS:
        result.pop(field, None)
    return result


def normalize_questions(questions, preserve_sources=False):
    if questions is None:
        return []
    if not isinstance(questions, list):
        raise ValueError("questions must be an array")
    if any(not isinstance(question, dict) for question in questions):
        raise ValueError("each question must be an object")
    return [
        _question_defaults(question if preserve_sources else _without_question_sources(question), index)
        for index, question in enumerate(questions)
    ]


def _normalize_patched_questions(questions, existing_questions):
    normalized = normalize_questions(questions)
    existing_by_id = {
        question.get("question_id"): question
        for question in existing_questions
        if question.get("question_id") is not None
    }
    for question in normalized:
        existing = existing_by_id.get(question.get("question_id"))
        if existing is None or _without_question_sources(existing) != question:
            continue
        for field in _QUESTION_SOURCE_FIELDS:
            if field in existing:
                question[field] = existing[field]
    return normalized


def _version(number, questions, state="draft"):
    return {"version": number, "state": state, "created_at": now(), "published_at": None, "questions": questions}


def survey_view(survey, include_versions=False):
    result = {
        "survey_id": str(survey["_id"]),
        "owner_user_id": str(survey["owner_user_id"]),
        "title": survey["title"],
        "description": survey.get("description", ""),
        "share_slug": survey["share_slug"],
        "status": survey["status"],
        "allow_anonymous": survey.get("allow_anonymous", False),
        "require_login_to_fill": survey.get("require_login_to_fill", True),
        "allow_multiple_submissions": survey.get("allow_multiple_submissions", False),
        "deadline_at": survey.get("deadline_at"),
        "closed_at": survey.get("closed_at"),
        "published_at": survey.get("published_at"),
        "current_version": survey.get("current_version"),
        "published_version": survey.get("published_version"),
    }
    if include_versions:
        result["versions"] = survey.get("versions", [])
    return result


def create_survey(database, owner_id, data):
    title = data.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("title is required")
    questions = normalize_questions(data.get("questions", []))
    created = now()
    survey = {
        "owner_user_id": owner_id,
        "title": title.strip(),
        "description": data.get("description", ""),
        "share_slug": _slug(),
        "status": "draft",
        "allow_anonymous": bool(data.get("allow_anonymous", False)),
        "require_login_to_fill": bool(data.get("require_login_to_fill", True)),
        "allow_multiple_submissions": bool(data.get("allow_multiple_submissions", False)),
        "deadline_at": parse_deadline(data.get("deadline_at")),
        "closed_at": None,
        "published_at": None,
        "created_at": created,
        "updated_at": created,
        "current_version": 1,
        "published_version": None,
        "versions": [_version(1, questions)],
    }
    try:
        result = database.surveys.insert_one(survey)
    except DuplicateKeyError:
        survey["share_slug"] = _slug()
        result = database.surveys.insert_one(survey)
    survey["_id"] = result.inserted_id
    return survey


def owner_survey(database, owner_id, survey_id):
    if not ObjectId.is_valid(survey_id):
        return None
    return database.surveys.find_one({"_id": ObjectId(survey_id), "owner_user_id": owner_id})


def current_version(survey):
    return next((version for version in survey.get("versions", []) if version["version"] == survey["current_version"]), None)


def published_version(survey):
    return next((version for version in survey.get("versions", []) if version["version"] == survey.get("published_version")), None)


def update_survey(database, survey, data, *, trusted_question_sources=False):
    current = current_version(survey)
    if current is None:
        raise ValueError("survey has no current version")
    versions = deepcopy(survey.get("versions", []))
    current = next((item for item in versions if item["version"] == survey["current_version"]), None)
    if current is None:
        raise ValueError("survey has no current version")
    if current["state"] != "draft":
        number = max(version["version"] for version in versions) + 1
        draft = _version(number, deepcopy(current["questions"]), "draft")
        versions.append(draft)
        current = draft
        survey["current_version"] = number
    if "title" in data:
        if not isinstance(data["title"], str) or not data["title"].strip():
            raise ValueError("title is required")
        survey["title"] = data["title"].strip()
    for field in ("description", "allow_anonymous", "require_login_to_fill", "allow_multiple_submissions"):
        if field in data:
            survey[field] = data[field]
    if "deadline_at" in data:
        survey["deadline_at"] = parse_deadline(data["deadline_at"])
    if "questions" in data:
        if trusted_question_sources:
            current["questions"] = normalize_questions(data["questions"], preserve_sources=True)
        else:
            current["questions"] = _normalize_patched_questions(data["questions"], current.get("questions", []))
    current["state"] = "draft"
    survey["versions"] = versions
    survey["updated_at"] = now()
    database.surveys.replace_one({"_id": survey["_id"]}, survey)
    return survey


def publish_survey(database, survey):
    version = current_version(survey)
    if version is None or version["state"] != "draft":
        raise ValueError("survey has no editable draft")
    result = validate_survey_definition(version["questions"])
    if not result["valid"]:
        raise DefinitionError(result["errors"])
    published_at = now()
    for item in survey["versions"]:
        if item["version"] == version["version"]:
            item["state"] = "published"
            item["published_at"] = published_at
    survey.update({"status": "published", "published_version": version["version"], "published_at": published_at, "updated_at": published_at})
    database.surveys.replace_one({"_id": survey["_id"]}, survey)
    return survey


class DefinitionError(ValueError):
    def __init__(self, errors):
        super().__init__("survey definition is invalid")
        self.errors = errors


def close_survey(database, survey):
    timestamp = now()
    database.surveys.update_one({"_id": survey["_id"]}, {"$set": {"status": "closed", "closed_at": timestamp, "updated_at": timestamp}})
    survey["status"], survey["closed_at"] = "closed", timestamp
    return survey


def public_survey(database, slug):
    survey = database.surveys.find_one({"share_slug": slug})
    if survey is None:
        return None
    version = published_version(survey)
    if version is None:
        return None
    return survey, version


def survey_is_open(survey):
    if survey.get("status") != "published" or survey.get("closed_at") is not None:
        return False
    deadline = survey.get("deadline_at")
    if deadline is None:
        return True
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    return deadline > now()


def submit_response(database, survey, version, user_id, answers):
    result = validate_submission(version["questions"], answers)
    if not result["valid"]:
        raise SubmissionError(result)
    key = None if survey.get("allow_multiple_submissions") else f"{survey['_id']}:{user_id}"
    response = {
        "survey_id": survey["_id"], "survey_owner_user_id": survey["owner_user_id"],
        "survey_version": version["version"], "survey_snapshot": {"title": survey["title"], "questions": deepcopy(version["questions"])},
        "respondent_user_id": user_id, "is_anonymous_to_owner": bool(survey.get("allow_anonymous")),
        "status": "submitted", "started_at": now(), "submitted_at": now(),
        "answers": list(answers.values()), "path": result["path"],
    }
    if key is not None:
        response["submission_key"] = key
    try:
        inserted = database.responses.insert_one(response)
    except DuplicateKeyError as exc:
        raise AlreadySubmittedError("survey already submitted by this account") from exc
    return {"response_id": str(inserted.inserted_id), "survey_id": str(survey["_id"]), "survey_version": version["version"], "submitted_at": response["submitted_at"], "path": result["path"]}


def validate_navigation_answer(question, answer):
    return validate_answer(question, answer)


class SubmissionError(ValueError):
    def __init__(self, result):
        super().__init__("submission is invalid")
        self.result = result


class AlreadySubmittedError(ValueError):
    pass


def calculate_statistics(database, survey, version_number=None, question_id=None, include_text=True):
    query = {"survey_id": survey["_id"], "status": "submitted"}
    if version_number is not None:
        query["survey_version"] = version_number
    responses = list(database.responses.find(query))
    versions = {version["version"]: version for version in survey.get("versions", [])}
    questions = []
    if not responses:
        fallback = published_version(survey) or current_version(survey)
        questions = [] if fallback is None else fallback.get("questions", [])
    for response in responses:
        snapshot_questions = response.get("survey_snapshot", {}).get("questions", versions.get(response.get("survey_version"), {}).get("questions", []))
        questions.extend(snapshot_questions)
    question_map = {question["question_id"]: question for question in questions}
    if question_id is not None and question_id not in question_map:
        raise KeyError(question_id)
    ids = [question_id] if question_id is not None else list(question_map)
    output = {"survey_id": str(survey["_id"]), "response_count": len(responses), "questions": {}}
    for current_id in ids:
        question = question_map.get(current_id, {})
        values = []
        for response in responses:
            for answer in response.get("answers", []):
                if answer.get("question_id") == current_id:
                    values.append(answer.get("value"))
        item = {"answered_count": len(values)}
        if question.get("type") == "single_choice":
            counts = {option.get("option_id"): 0 for option in question.get("options", [])}
            for value in values:
                if value in counts:
                    counts[value] += 1
            item["option_counts"] = counts
        elif question.get("type") == "multiple_choice":
            counts = {option.get("option_id"): 0 for option in question.get("options", [])}
            for value in values:
                for option_id in value or []:
                    if option_id in counts:
                        counts[option_id] += 1
            item["option_counts"] = counts
        elif question.get("type") == "text_input":
            if include_text:
                item["answers"] = values
        elif question.get("type") == "number_input":
            item["average"] = sum(values) / len(values) if values else None
        output["questions"][current_id] = item
    return output
