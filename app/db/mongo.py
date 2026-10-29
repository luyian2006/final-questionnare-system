from fastapi import FastAPI
from pymongo import MongoClient
from pymongo.database import Database

from app.core.config import settings


def create_mongo_client() -> MongoClient:
    return MongoClient(settings.mongodb_uri, serverSelectionTimeoutMS=1000)


def get_mongo_client(app: FastAPI) -> MongoClient:
    client = getattr(app.state, "mongo_client", None)
    if client is None:
        client = create_mongo_client()
        app.state.mongo_client = client
    return client


def get_database(app: FastAPI) -> Database:
    database = getattr(app.state, "mongo_database", None)
    if database is None:
        client = get_mongo_client(app)
        database = client[settings.mongodb_database]
        app.state.mongo_database = database
    return database


def ping_database(app: FastAPI) -> None:
    get_database(app).command("ping")


def ensure_indexes(database: Database) -> None:
    database.users.create_index("username_normalized", unique=True, name="username_unique")
    database.users.create_index([("created_at", -1)], name="users_created_at")
    database.surveys.create_index(
        [("share_slug", 1)], unique=True, name="share_slug_unique"
    )
    database.surveys.create_index(
        [("owner_user_id", 1), ("updated_at", -1)], name="surveys_owner_updated"
    )
    database.responses.create_index(
        [("survey_id", 1), ("submitted_at", -1)], name="responses_survey_submitted"
    )
    database.responses.create_index(
        [("survey_id", 1), ("survey_version", 1)], name="responses_survey_version"
    )
    database.responses.create_index(
        [("respondent_user_id", 1), ("survey_id", 1)], name="responses_user_survey"
    )
    database.responses.create_index(
        [("survey_id", 1), ("submission_key", 1)],
        unique=True,
        partialFilterExpression={"submission_key": {"$exists": True}},
        name="responses_submission_unique",
    )
    database.responses.create_index(
        [("survey_id", 1), ("answers.question_id", 1)], name="responses_question"
    )
    database.question_items.create_index(
        [("owner_user_id", 1), ("updated_at", -1)], name="question_items_owner_updated"
    )
    database.question_items.create_index(
        [("is_shared", 1), ("updated_at", -1)], name="question_items_shared_updated"
    )
    database.question_versions.create_index(
        [("question_item_id", 1), ("version_number", 1)],
        unique=True,
        name="question_versions_item_number_unique",
    )
    database.question_versions.create_index(
        [("question_item_id", 1), ("created_at", -1)], name="question_versions_item_created"
    )
    database.responses.create_index(
        [("survey_snapshot.questions.source_question_version_id", 1), ("submitted_at", -1)],
        name="responses_source_question_version",
    )


def close_mongo_client(app: FastAPI) -> None:
    client = getattr(app.state, "mongo_client", None)
    if client is not None:
        client.close()
        app.state.mongo_client = None
        app.state.mongo_database = None
