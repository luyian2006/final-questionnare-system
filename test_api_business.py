from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from bson import ObjectId
from fastapi.testclient import TestClient
from pymongo.errors import DuplicateKeyError

from app.main import app


def _matches(document, query):
    return all(document.get(key) == value for key, value in query.items())


class MemoryCursor(list):
    def sort(self, key, direction):
        super().sort(key=lambda item: item.get(key), reverse=direction < 0)
        return self


class MemoryCollection:
    def __init__(self, name):
        self.name = name
        self.documents = []

    def create_index(self, *args, **kwargs):
        return kwargs.get("name", "index")

    def find_one(self, query):
        found = next((item for item in self.documents if _matches(item, query)), None)
        return deepcopy(found) if found is not None else None

    def find(self, query):
        return MemoryCursor(deepcopy([item for item in self.documents if _matches(item, query)]))

    def insert_one(self, document):
        candidate = deepcopy(document)
        if self.name == "users" and any(
            item.get("username_normalized") == candidate.get("username_normalized")
            for item in self.documents
        ):
            raise DuplicateKeyError("duplicate username")
        if self.name == "surveys" and any(
            item.get("share_slug") == candidate.get("share_slug")
            for item in self.documents
        ):
            raise DuplicateKeyError("duplicate share slug")
        if self.name == "responses" and candidate.get("submission_key") is not None and any(
            item.get("survey_id") == candidate.get("survey_id")
            and item.get("submission_key") == candidate.get("submission_key")
            for item in self.documents
        ):
            raise DuplicateKeyError("duplicate submission")
        if self.name == "question_versions" and any(
            item.get("question_item_id") == candidate.get("question_item_id")
            and item.get("version_number") == candidate.get("version_number")
            for item in self.documents
        ):
            raise DuplicateKeyError("duplicate question version")
        candidate.setdefault("_id", ObjectId())
        self.documents.append(candidate)
        document["_id"] = candidate["_id"]
        return SimpleNamespace(inserted_id=candidate["_id"])

    def update_one(self, query, update):
        for item in self.documents:
            if _matches(item, query):
                item.update(deepcopy(update.get("$set", {})))
                return SimpleNamespace(matched_count=1, modified_count=1)
        return SimpleNamespace(matched_count=0, modified_count=0)

    def replace_one(self, query, replacement):
        for index, item in enumerate(self.documents):
            if _matches(item, query):
                self.documents[index] = deepcopy(replacement)
                return SimpleNamespace(matched_count=1, modified_count=1)
        return SimpleNamespace(matched_count=0, modified_count=0)


class MemoryDatabase:
    def __init__(self):
        self.users = MemoryCollection("users")
        self.surveys = MemoryCollection("surveys")
        self.responses = MemoryCollection("responses")
        self.question_items = MemoryCollection("question_items")
        self.question_versions = MemoryCollection("question_versions")

    def command(self, name):
        assert name == "ping"
        return {"ok": 1}


@pytest.fixture
def api():
    database = MemoryDatabase()
    app.state.mongo_database = database
    app.state.mongo_client = None
    with TestClient(app) as client:
        yield client, database
    app.state.mongo_database = None


def register_and_login(client, username):
    registered = client.post("/auth/register", json={"username": username, "password": "secret123"})
    assert registered.status_code == 201
    logged_in = client.post("/auth/login", json={"username": username.upper(), "password": "secret123"})
    assert logged_in.status_code == 200
    return {"Authorization": f"Bearer {logged_in.json()['access_token']}"}


def choice_question(question_id, order, multiple=False, required=True):
    return {
        "question_id": question_id,
        "type": "multiple_choice" if multiple else "single_choice",
        "title": question_id,
        "required": required,
        "order": order,
        "options": [
            {"option_id": "a", "label": "A", "order": 1},
            {"option_id": "b", "label": "B", "order": 2},
        ],
        "validation": {},
        "jump_rules": [],
    }


def answer(question_id, question_type, value):
    return {"question_id": question_id, "type": question_type, "value": value}


def create_and_publish(client, headers, questions, **settings):
    payload = {"title": "Course survey", "questions": questions, **settings}
    created = client.post("/surveys", headers=headers, json=payload)
    assert created.status_code == 201
    survey_id = created.json()["survey_id"]
    published = client.post(f"/surveys/{survey_id}/publish", headers=headers)
    assert published.status_code == 200
    return survey_id, published.json()["share_slug"]


def test_registration_login_and_owner_isolation(api):
    client, database = api
    alice = register_and_login(client, "Alice")
    duplicate = client.post("/auth/register", json={"username": " alice ", "password": "secret123"})
    assert duplicate.status_code == 409
    assert database.users.documents[0]["password_hash"] != "secret123"
    assert "secret123" not in database.users.documents[0]["password_hash"]

    created = client.post("/surveys", headers=alice, json={"title": "Mine"})
    survey_id = created.json()["survey_id"]
    bob = register_and_login(client, "bob")
    assert client.get(f"/surveys/{survey_id}", headers=bob).status_code == 404
    assert client.get("/surveys", headers=bob).json() == []
    assert len(client.get("/surveys", headers=alice).json()) == 1


def test_publish_validation_versioning_and_close(api):
    client, _ = api
    owner = register_and_login(client, "owner")
    draft = client.post("/surveys", headers=owner, json={"title": "Empty"})
    invalid = client.post(f"/surveys/{draft.json()['survey_id']}/publish", headers=owner)
    assert invalid.status_code == 422
    assert invalid.json()["detail"]["errors"][0]["code"] == "empty_survey"

    survey_id, slug = create_and_publish(client, owner, [choice_question("q1", 1)])
    edited = client.patch(
        f"/surveys/{survey_id}", headers=owner, json={"questions": [choice_question("q2", 1)]}
    )
    assert edited.status_code == 200
    body = edited.json()
    assert body["current_version"] == 2
    assert body["published_version"] == 1
    assert body["versions"][0]["questions"][0]["question_id"] == "q1"
    assert body["versions"][1]["questions"][0]["question_id"] == "q2"

    closed = client.post(f"/surveys/{survey_id}/close", headers=owner)
    assert closed.status_code == 200
    assert closed.json()["status"] == "closed"
    assert client.get(f"/surveys/share/{slug}").status_code == 410


def test_conditional_navigation_submission_and_duplicate_policy(api):
    client, database = api
    owner = register_and_login(client, "jump-owner")
    q1 = choice_question("q1", 1)
    q1["jump_rules"] = [{
        "rule_id": "skip-q2", "priority": 1,
        "condition": {"operator": "equals", "value": "a"},
        "target": {"type": "question", "question_id": "q3"},
    }]
    q2 = {"question_id": "q2", "type": "text_input", "title": "Skipped", "required": True, "order": 2, "validation": {}, "jump_rules": []}
    q3 = {"question_id": "q3", "type": "text_input", "title": "Finish", "required": True, "order": 3, "validation": {"min_length": 2}, "jump_rules": []}
    survey_id, slug = create_and_publish(client, owner, [q1, q2, q3])
    assert client.get(f"/surveys/share/{slug}").status_code == 200
    assert client.post(f"/surveys/share/{slug}/next", json={"question_id": "q1", "answers": {}}).status_code == 401
    assert client.post(f"/surveys/share/{slug}/submit", json={"answers": {}}).status_code == 401
    filler = register_and_login(client, "filler")
    q1_answer = answer("q1", "single_choice", "a")

    navigation = client.post(
        f"/surveys/share/{slug}/next", headers=filler,
        json={"question_id": "q1", "answers": {"q1": q1_answer}},
    )
    assert navigation.status_code == 200
    assert navigation.json() == {"action": "goto_question", "question_id": "q3", "matched_rule_id": "skip-q2"}

    invalid_navigation = client.post(
        f"/surveys/share/{slug}/next", headers=filler,
        json={"question_id": "q1", "answers": {"q1": answer("q1", "single_choice", "unknown")}},
    )
    assert invalid_navigation.status_code == 422
    assert invalid_navigation.json()["detail"]["code"] == "invalid_answer_option"

    answers = {"q1": q1_answer, "q3": answer("q3", "text_input", "ok")}
    submitted = client.post(f"/surveys/share/{slug}/submit", headers=filler, json={"answers": answers})
    assert submitted.status_code == 201
    assert submitted.json()["path"] == ["q1", "q3"]
    assert database.responses.documents[0]["survey_id"] == ObjectId(survey_id)

    duplicate = client.post(f"/surveys/share/{slug}/submit", headers=filler, json={"answers": answers})
    assert duplicate.status_code == 409

    forged = {**answers, "q2": answer("q2", "text_input", "should fail")}
    other = register_and_login(client, "other-filler")
    rejected = client.post(f"/surveys/share/{slug}/submit", headers=other, json={"answers": forged})
    assert rejected.status_code == 422
    assert rejected.json()["detail"]["errors"][0]["code"] == "answer_not_on_path"


def test_all_question_statistics(api):
    client, _ = api
    owner = register_and_login(client, "stats-owner")
    questions = [
        choice_question("single", 1),
        choice_question("multi", 2, multiple=True),
        {"question_id": "text", "type": "text_input", "title": "Text", "required": True, "order": 3, "validation": {}, "jump_rules": []},
        {"question_id": "number", "type": "number_input", "title": "Number", "required": True, "order": 4, "validation": {}, "jump_rules": []},
    ]
    survey_id, slug = create_and_publish(client, owner, questions, allow_anonymous=True)
    values = [("one", "a", ["a", "b"], "first", 10), ("two", "b", ["b"], "second", 20)]
    for username, single, multi, text, number in values:
        filler = register_and_login(client, username)
        answers = {
            "single": answer("single", "single_choice", single),
            "multi": answer("multi", "multiple_choice", multi),
            "text": answer("text", "text_input", text),
            "number": answer("number", "number_input", number),
        }
        assert client.post(f"/surveys/share/{slug}/submit", headers=filler, json={"answers": answers}).status_code == 201

    statistics = client.get(f"/surveys/{survey_id}/statistics", headers=owner)
    assert statistics.status_code == 200
    data = statistics.json()
    assert data["response_count"] == 2
    assert data["questions"]["single"]["option_counts"] == {"a": 1, "b": 1}
    assert data["questions"]["multi"]["option_counts"] == {"a": 1, "b": 2}
    assert data["questions"]["text"]["answers"] == ["first", "second"]
    assert data["questions"]["number"]["average"] == 15
    assert "respondent_user_id" not in statistics.json()
    assert client.get(f"/surveys/{survey_id}/statistics", headers=register_and_login(client, "intruder")).status_code == 404


def test_deadline_blocks_published_share_and_submission(api):
    client, _ = api
    owner = register_and_login(client, "deadline-owner")
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    created = client.post(
        "/surveys",
        headers=owner,
        json={"title": "Expired", "deadline_at": past, "questions": [choice_question("q1", 1)]},
    )
    assert created.status_code == 201
    survey_id = created.json()["survey_id"]
    published = client.post(f"/surveys/{survey_id}/publish", headers=owner)
    assert published.status_code == 200
    slug = published.json()["share_slug"]
    assert client.get(f"/surveys/share/{slug}").status_code == 410
    filler = register_and_login(client, "deadline-filler")
    assert client.post(
        f"/surveys/share/{slug}/submit",
        headers=filler,
        json={"answers": {"q1": answer("q1", "single_choice", "a")}},
    ).status_code == 410


def test_allow_multiple_submissions_persists_each_response(api):
    client, database = api
    owner = register_and_login(client, "repeat-owner")
    survey_id, slug = create_and_publish(
        client,
        owner,
        [choice_question("q1", 1)],
        allow_multiple_submissions=True,
    )
    filler = register_and_login(client, "repeat-filler")
    payload = {"answers": {"q1": answer("q1", "single_choice", "a")}}
    first = client.post(f"/surveys/share/{slug}/submit", headers=filler, json=payload)
    second = client.post(f"/surveys/share/{slug}/submit", headers=filler, json=payload)
    assert first.status_code == 201
    assert second.status_code == 201
    assert len([item for item in database.responses.documents if item["survey_id"] == ObjectId(survey_id)]) == 2


def library_question(title="Library choice", kind="single_choice", rules=None):
    question = {
        "question_id": "library_source", "type": kind, "title": title,
        "description": "Reusable question", "required": True, "order": 1,
        "validation": {}, "jump_rules": rules or [],
    }
    if kind in {"single_choice", "multiple_choice"}:
        question["options"] = [
            {"option_id": "a", "label": "A", "order": 1},
            {"option_id": "b", "label": "B", "order": 2},
        ]
    return question


def create_library_item(client, headers, *, title="Library choice", kind="single_choice", shared=False, rules=None):
    result = client.post("/question-items", headers=headers, json={
        "display_title": title, "is_shared": shared,
        "content": library_question(title, kind, rules),
    })
    assert result.status_code == 201, result.text
    return result.json()


def add_library_question(client, headers, survey_id, item_id, version_id):
    result = client.post(f"/surveys/{survey_id}/questions/from-library", headers=headers, json={
        "question_item_id": item_id, "question_version_id": version_id,
    })
    assert result.status_code == 200, result.text
    body = result.json()
    current = next(v for v in body["versions"] if v["version"] == body["current_version"])
    return body, current["questions"][-1]


def current_questions(survey):
    return next(
        version["questions"]
        for version in survey["versions"]
        if version["version"] == survey["current_version"]
    )


def test_normal_survey_writes_cannot_forge_question_sources(api):
    client, _ = api
    owner = register_and_login(client, "source-forgery")
    forged = library_question("Forged source")
    forged["source_question_item_id"] = "forged-item"
    forged["source_question_version_id"] = "forged-version"

    created = client.post("/surveys", headers=owner, json={"title": "Created", "questions": [forged]})
    assert created.status_code == 201
    assert "source_question_item_id" not in current_questions(created.json())[0]
    assert "source_question_version_id" not in current_questions(created.json())[0]

    forged = deepcopy(current_questions(created.json())[0])
    forged["source_question_item_id"] = "forged-item"
    forged["source_question_version_id"] = "forged-version"
    patched = client.patch(
        f"/surveys/{created.json()['survey_id']}",
        headers=owner,
        json={"questions": [forged]},
    )
    assert patched.status_code == 200
    assert "source_question_item_id" not in current_questions(patched.json())[0]
    assert "source_question_version_id" not in current_questions(patched.json())[0]


def test_patch_preserves_only_unchanged_server_question_sources(api):
    client, _ = api
    owner = register_and_login(client, "source-preservation")
    item = create_library_item(client, owner)
    survey = client.post("/surveys", headers=owner, json={"title": "Original"}).json()
    survey, copied = add_library_question(
        client, owner, survey["survey_id"], item["question_item_id"], item["current_version_id"]
    )

    renamed = client.patch(
        f"/surveys/{survey['survey_id']}", headers=owner, json={"title": "Renamed"}
    )
    assert renamed.status_code == 200
    unchanged = current_questions(renamed.json())[0]
    assert unchanged["source_question_item_id"] == item["question_item_id"]
    assert unchanged["source_question_version_id"] == item["current_version_id"]

    copied["source_question_item_id"] = "client-replaced-item"
    copied["source_question_version_id"] = "client-replaced-version"
    echoed = client.patch(
        f"/surveys/{survey['survey_id']}", headers=owner, json={"questions": [copied]}
    )
    assert echoed.status_code == 200
    server_sources = current_questions(echoed.json())[0]
    assert server_sources["source_question_item_id"] == item["question_item_id"]
    assert server_sources["source_question_version_id"] == item["current_version_id"]

    server_sources["title"] = "Locally edited content"
    edited = client.patch(
        f"/surveys/{survey['survey_id']}", headers=owner, json={"questions": [server_sources]}
    )
    assert edited.status_code == 200
    edited_question = current_questions(edited.json())[0]
    assert "source_question_item_id" not in edited_question
    assert "source_question_version_id" not in edited_question


def test_edited_library_copy_is_excluded_but_normal_reuse_still_counts(api):
    client, _ = api
    owner = register_and_login(client, "source-statistics")
    item = create_library_item(client, owner)
    item_id, version_id = item["question_item_id"], item["current_version_id"]

    normal = client.post("/surveys", headers=owner, json={"title": "Normal reuse"}).json()
    normal, normal_question = add_library_question(client, owner, normal["survey_id"], item_id, version_id)
    normal = client.post(f"/surveys/{normal['survey_id']}/publish", headers=owner).json()
    assert client.post(
        f"/surveys/share/{normal['share_slug']}/submit",
        headers=owner,
        json={"answers": {normal_question["question_id"]: answer(normal_question["question_id"], "single_choice", "a")}},
    ).status_code == 201

    edited = client.post("/surveys", headers=owner, json={"title": "Edited reuse"}).json()
    edited, edited_question = add_library_question(client, owner, edited["survey_id"], item_id, version_id)
    edited_question["title"] = "Changed after copying"
    edited = client.patch(
        f"/surveys/{edited['survey_id']}", headers=owner, json={"questions": [edited_question]}
    ).json()
    assert "source_question_version_id" not in current_questions(edited)[0]
    edited = client.post(f"/surveys/{edited['survey_id']}/publish", headers=owner).json()
    assert client.post(
        f"/surveys/share/{edited['share_slug']}/submit",
        headers=owner,
        json={"answers": {edited_question["question_id"]: answer(edited_question["question_id"], "single_choice", "b")}},
    ).status_code == 201

    stats = client.get(
        f"/question-items/{item_id}/statistics?version_id={version_id}", headers=owner
    )
    assert stats.status_code == 200
    assert stats.json()["valid_answer_count"] == 1
    assert {option["option_id"]: option["count"] for option in stats.json()["options"]} == {"a": 1, "b": 0}


def test_question_version_create_edit_restore_and_auth(api):
    client, database = api
    assert client.get("/question-items").status_code == 401
    alice = register_and_login(client, "library-owner")
    item = create_library_item(client, alice)
    item_id, v1 = item["question_item_id"], item["current_version"]
    changed = deepcopy(v1["content"])
    changed["title"] = "Edited title"
    v2_response = client.post(f"/question-items/{item_id}/versions", headers=alice, json={
        "content": changed, "based_on_version_id": v1["version_id"],
    })
    assert v2_response.status_code == 201
    v2 = v2_response.json()
    v3_response = client.post(
        f"/question-items/{item_id}/versions/{v1['version_id']}/restore", headers=alice,
    )
    assert v3_response.status_code == 201
    v3 = v3_response.json()
    assert [v1["version_number"], v2["version_number"], v3["version_number"]] == [1, 2, 3]
    assert v1["content"]["title"] == v3["content"]["title"] == "Library choice"
    assert v2["content"]["title"] == "Edited title"
    assert v3["restored_from_version_id"] == v1["version_id"]
    assert len(database.question_versions.documents) == 3


def test_shared_question_cannot_be_edited_but_can_be_derived(api):
    client, _ = api
    alice = register_and_login(client, "share-owner")
    original = create_library_item(client, alice, shared=True)
    bob = register_and_login(client, "share-reader")
    assert [item["question_item_id"] for item in client.get("/question-items?scope=shared", headers=bob).json()] == [original["question_item_id"]]
    assert client.post(f"/question-items/{original['question_item_id']}/versions", headers=bob, json={
        "content": library_question("Stolen edit"),
    }).status_code == 404
    assert client.get(
        f"/question-items/{original['question_item_id']}/statistics?version_id={original['current_version_id']}",
        headers=bob,
    ).status_code == 404
    bob_survey = client.post("/surveys", headers=bob, json={"title": "Uses shared question"}).json()
    _, bob_copy = add_library_question(
        client, bob, bob_survey["survey_id"], original["question_item_id"], original["current_version_id"]
    )
    assert bob_copy["source_question_version_id"] == original["current_version_id"]
    derived_response = client.post(f"/question-items/{original['question_item_id']}/derive", headers=bob, json={
        "version_id": original["current_version_id"], "display_title": "Bob copy",
    })
    assert derived_response.status_code == 201, derived_response.text
    derived = derived_response.json()
    assert derived["owner_user_id"] != original["owner_user_id"]
    assert derived["derived_from_item_id"] == original["question_item_id"]
    assert derived["derived_from_version_id"] == original["current_version_id"]
    edited = deepcopy(derived["current_version"]["content"])
    edited["title"] = "Bob only"
    assert client.post(f"/question-items/{derived['question_item_id']}/versions", headers=bob, json={"content": edited}).status_code == 201
    assert client.get(f"/question-items/{original['question_item_id']}", headers=alice).json()["current_version"]["content"]["title"] == "Library choice"


def test_question_snapshots_usage_repeats_and_unsharing(api):
    client, _ = api
    alice = register_and_login(client, "snapshot-owner")
    item = create_library_item(client, alice, shared=True)
    survey = client.post("/surveys", headers=alice, json={"title": "Snapshot survey"}).json()
    _, first = add_library_question(client, alice, survey["survey_id"], item["question_item_id"], item["current_version_id"])
    _, second = add_library_question(client, alice, survey["survey_id"], item["question_item_id"], item["current_version_id"])
    assert first["question_id"] != second["question_id"]
    assert first["source_question_item_id"] == item["question_item_id"]
    assert first["source_question_version_id"] == item["current_version_id"]
    assert client.patch(f"/question-items/{item['question_item_id']}", headers=alice, json={"is_shared": False}).status_code == 200
    changed = deepcopy(item["current_version"]["content"])
    changed["title"] = "Library changed later"
    assert client.post(f"/question-items/{item['question_item_id']}/versions", headers=alice, json={"content": changed}).status_code == 201
    body = client.get(f"/surveys/{survey['survey_id']}", headers=alice).json()
    current = next(v for v in body["versions"] if v["version"] == body["current_version"])
    assert [q["title"] for q in current["questions"]] == ["Library choice", "Library choice"]
    usage = client.get(f"/question-items/{item['question_item_id']}/usage", headers=alice)
    assert usage.status_code == 200 and usage.json()["usage_count"] == 2


def test_added_question_with_missing_jump_target_fails_publish(api):
    client, _ = api
    alice = register_and_login(client, "library-jump-owner")
    rule = {"rule_id": "external", "priority": 1, "condition": {"operator": "equals", "value": "a"}, "target": {"type": "question", "question_id": "missing_target"}}
    item = create_library_item(client, alice, rules=[rule])
    survey = client.post("/surveys", headers=alice, json={"title": "Jump survey"}).json()
    add_library_question(client, alice, survey["survey_id"], item["question_item_id"], item["current_version_id"])
    published = client.post(f"/surveys/{survey['survey_id']}/publish", headers=alice)
    assert published.status_code == 422
    assert published.json()["detail"]["errors"][0]["code"] == "invalid_jump_target"


@pytest.mark.parametrize("kind,values", [
    ("single_choice", ["a", "b"]),
    ("multiple_choice", [["a", "b"], ["a"]]),
    ("number_input", [2, 8]),
    ("text_input", ["first", "second"]),
])
def test_cross_survey_statistics_use_exact_version_and_valid_answers(api, kind, values):
    client, _ = api
    owner = register_and_login(client, f"library-stats-{kind}")
    item = create_library_item(client, owner, kind=kind)
    item_id, v1_id = item["question_item_id"], item["current_version_id"]
    local_ids, slugs = [], []
    for index in range(2):
        survey = client.post("/surveys", headers=owner, json={"title": f"Survey {index}"}).json()
        _, question = add_library_question(client, owner, survey["survey_id"], item_id, v1_id)
        published = client.post(f"/surveys/{survey['survey_id']}/publish", headers=owner).json()
        local_ids.append(question["question_id"])
        slugs.append(published["share_slug"])
    for index, value in enumerate(values):
        payload = {local_ids[index]: answer(local_ids[index], kind, value)}
        assert client.post(f"/surveys/share/{slugs[index]}/submit", headers=owner, json={"answers": payload}).status_code == 201

    changed = deepcopy(item["current_version"]["content"])
    changed["title"] = "New incompatible version"
    v2 = client.post(f"/question-items/{item_id}/versions", headers=owner, json={"content": changed}).json()
    survey = client.post("/surveys", headers=owner, json={"title": "Different version"}).json()
    _, question = add_library_question(client, owner, survey["survey_id"], item_id, v2["version_id"])
    published = client.post(f"/surveys/{survey['survey_id']}/publish", headers=owner).json()
    payload = {question["question_id"]: answer(question["question_id"], kind, values[0])}
    assert client.post(f"/surveys/share/{published['share_slug']}/submit", headers=owner, json={"answers": payload}).status_code == 201

    stats = client.get(f"/question-items/{item_id}/statistics?version_id={v1_id}", headers=owner)
    assert stats.status_code == 200, stats.text
    body = stats.json()
    assert body["valid_answer_count"] == body["response_count"] == body["survey_count"] == 2
    if kind in {"single_choice", "multiple_choice"}:
        options = {option["option_id"]: option for option in body["options"]}
        expected_counts = {"a": 1, "b": 1} if kind == "single_choice" else {"a": 2, "b": 1}
        assert {key: value["count"] for key, value in options.items()} == expected_counts
        assert body["denominator"] == "valid_answer_count"
    elif kind == "number_input":
        assert body["average"] == 5
        assert body["minimum"] == 2
        assert body["maximum"] == 8
    else:
        assert body["text_answer_count"] == 2
