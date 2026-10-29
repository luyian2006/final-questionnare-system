from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.dependencies import get_current_user, get_db
from app.question_services import (
    QuestionAccessError,
    QuestionDefinitionError,
    add_version_to_survey,
    create_question_item,
    create_version,
    cross_survey_statistics,
    derive_question,
    get_question_item,
    get_version,
    list_question_items,
    list_versions,
    question_usage,
    restore_version,
    update_question_item,
)
from app.services import owner_survey, survey_view


router = APIRouter()


def _not_found(message="Question not found"):
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)


def _call(action):
    try:
        return action()
    except QuestionDefinitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_question_definition", "errors": exc.errors},
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/question-items")
def question_items(scope: str = "all", user=Depends(get_current_user), database=Depends(get_db)):
    return _call(lambda: list_question_items(database, user["_id"], scope))


@router.post("/question-items", status_code=status.HTTP_201_CREATED)
def create_item(payload: dict[str, Any], user=Depends(get_current_user), database=Depends(get_db)):
    return _call(lambda: create_question_item(database, user["_id"], payload))


@router.get("/question-items/{item_id}")
def item_detail(item_id: str, user=Depends(get_current_user), database=Depends(get_db)):
    result = get_question_item(database, user["_id"], item_id)
    return result if result is not None else _not_found()


@router.patch("/question-items/{item_id}")
def edit_item(item_id: str, payload: dict[str, Any], user=Depends(get_current_user), database=Depends(get_db)):
    result = _call(lambda: update_question_item(database, user["_id"], item_id, payload))
    return result if result is not None else _not_found()


@router.get("/question-items/{item_id}/versions")
def item_versions(item_id: str, user=Depends(get_current_user), database=Depends(get_db)):
    result = list_versions(database, user["_id"], item_id)
    return result if result is not None else _not_found()


@router.post("/question-items/{item_id}/versions", status_code=status.HTTP_201_CREATED)
def new_version(item_id: str, payload: dict[str, Any], user=Depends(get_current_user), database=Depends(get_db)):
    result = _call(lambda: create_version(database, user["_id"], item_id, payload))
    return result if result is not None else _not_found()


@router.get("/question-items/{item_id}/versions/{version_id}")
def version_detail(item_id: str, version_id: str, user=Depends(get_current_user), database=Depends(get_db)):
    result = get_version(database, user["_id"], item_id, version_id)
    return result if result is not None else _not_found("Question version not found")


@router.post("/question-items/{item_id}/versions/{version_id}/restore", status_code=status.HTTP_201_CREATED)
def restore(item_id: str, version_id: str, user=Depends(get_current_user), database=Depends(get_db)):
    result = _call(lambda: restore_version(database, user["_id"], item_id, version_id))
    return result if result is not None else _not_found()


@router.post("/question-items/{item_id}/derive", status_code=status.HTTP_201_CREATED)
def derive(item_id: str, payload: dict[str, Any], user=Depends(get_current_user), database=Depends(get_db)):
    result = _call(lambda: derive_question(database, user["_id"], item_id, payload))
    return result if result is not None else _not_found()


@router.get("/question-items/{item_id}/usage")
def usage(item_id: str, user=Depends(get_current_user), database=Depends(get_db)):
    result = question_usage(database, user["_id"], item_id)
    return result if result is not None else _not_found()


@router.get("/question-items/{item_id}/statistics")
def statistics(item_id: str, version_id: str, user=Depends(get_current_user), database=Depends(get_db)):
    result = _call(lambda: cross_survey_statistics(database, user["_id"], item_id, version_id))
    return result if result is not None else _not_found()


@router.post("/surveys/{survey_id}/questions/from-library")
def add_library_question(
    survey_id: str,
    payload: dict[str, Any],
    user=Depends(get_current_user),
    database=Depends(get_db),
):
    survey = owner_survey(database, user["_id"], survey_id)
    if survey is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Survey not found")
    if survey.get("status") == "closed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Closed survey cannot be edited")
    try:
        updated = add_version_to_survey(
            database,
            user["_id"],
            survey,
            payload.get("question_item_id"),
            payload.get("question_version_id"),
        )
    except QuestionAccessError as exc:
        _not_found(str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return survey_view(updated, include_versions=True)
