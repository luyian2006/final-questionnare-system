from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.algorithms.jump import resolve_next_step
from app.dependencies import get_current_user, get_db
from app.services import (
    AlreadySubmittedError,
    DefinitionError,
    SubmissionError,
    calculate_statistics,
    close_survey,
    create_survey,
    login,
    owner_survey,
    public_survey,
    publish_survey,
    public_user,
    register,
    submit_response,
    survey_is_open,
    survey_view,
    update_survey,
)


router = APIRouter()


def _bad_request(message):
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message)


def _owner(database, user, survey_id):
    survey = owner_survey(database, user["_id"], survey_id)
    if survey is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Survey not found")
    return survey


@router.post("/auth/register", status_code=status.HTTP_201_CREATED)
def register_endpoint(payload: dict[str, Any], database=Depends(get_db)):
    try:
        return register(database, payload.get("username", ""), payload.get("password", ""))
    except ValueError as exc:
        if "already exists" in str(exc):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
        _bad_request(str(exc))


@router.post("/auth/login")
def login_endpoint(payload: dict[str, Any], database=Depends(get_db)):
    try:
        return login(database, payload.get("username", ""), payload.get("password", ""))
    except PermissionError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")


@router.get("/auth/me")
def current_user_endpoint(user=Depends(get_current_user)):
    return public_user(user)


@router.post("/surveys", status_code=status.HTTP_201_CREATED)
def create_survey_endpoint(payload: dict[str, Any], user=Depends(get_current_user), database=Depends(get_db)):
    try:
        return survey_view(create_survey(database, user["_id"], payload), include_versions=True)
    except ValueError as exc:
        _bad_request(str(exc))


@router.get("/surveys")
def list_surveys(user=Depends(get_current_user), database=Depends(get_db)):
    return [survey_view(item) for item in database.surveys.find({"owner_user_id": user["_id"]}).sort("updated_at", -1)]


@router.get("/surveys/share/{share_slug}")
def get_shared_survey(share_slug: str, database=Depends(get_db)):
    found = public_survey(database, share_slug)
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Published survey not found")
    survey, version = found
    if not survey_is_open(survey):
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Survey is closed or expired")
    result = survey_view(survey)
    result["questions"] = version["questions"]
    result["version"] = version["version"]
    return result


@router.get("/surveys/{survey_id}")
def get_survey(survey_id: str, user=Depends(get_current_user), database=Depends(get_db)):
    return survey_view(_owner(database, user, survey_id), include_versions=True)


@router.patch("/surveys/{survey_id}")
def edit_survey(survey_id: str, payload: dict[str, Any], user=Depends(get_current_user), database=Depends(get_db)):
    survey = _owner(database, user, survey_id)
    if survey.get("status") == "closed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Closed survey cannot be edited")
    try:
        return survey_view(update_survey(database, survey, payload), include_versions=True)
    except ValueError as exc:
        _bad_request(str(exc))


@router.post("/surveys/{survey_id}/publish")
def publish_survey_endpoint(survey_id: str, user=Depends(get_current_user), database=Depends(get_db)):
    survey = _owner(database, user, survey_id)
    try:
        return survey_view(publish_survey(database, survey), include_versions=True)
    except DefinitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_survey_definition", "errors": exc.errors},
        )
    except ValueError as exc:
        _bad_request(str(exc))


@router.post("/surveys/{survey_id}/close")
def close_survey_endpoint(survey_id: str, user=Depends(get_current_user), database=Depends(get_db)):
    return survey_view(close_survey(database, _owner(database, user, survey_id)), include_versions=True)


def _shared_open(database, share_slug):
    found = public_survey(database, share_slug)
    if found is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Published survey not found")
    if not survey_is_open(found[0]):
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Survey is closed or expired")
    return found


@router.post("/surveys/share/{share_slug}/next")
def next_question(share_slug: str, payload: dict[str, Any], user=Depends(get_current_user), database=Depends(get_db)):
    _, version = _shared_open(database, share_slug)
    result = resolve_next_step(version["questions"], payload.get("question_id"), payload.get("answers", {}))
    if result.get("action") == "error":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=result)
    return result


@router.post("/surveys/share/{share_slug}/submit", status_code=status.HTTP_201_CREATED)
def submit_survey(share_slug: str, payload: dict[str, Any], user=Depends(get_current_user), database=Depends(get_db)):
    survey, version = _shared_open(database, share_slug)
    try:
        return submit_response(database, survey, version, user["_id"], payload.get("answers", {}))
    except SubmissionError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.result)
    except AlreadySubmittedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get("/surveys/{survey_id}/statistics")
def survey_statistics(survey_id: str, version: int | None = None, question_id: str | None = None, include_text: bool = True, user=Depends(get_current_user), database=Depends(get_db)):
    try:
        return calculate_statistics(database, _owner(database, user, survey_id), version, question_id, include_text)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Question not found")
