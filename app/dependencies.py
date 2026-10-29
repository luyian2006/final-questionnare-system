from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from bson import ObjectId

from app.core.security import read_access_token
from app.db.mongo import get_database


bearer_scheme = HTTPBearer(auto_error=False)


def get_db(request: Request):
    return get_database(request.app)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    database=Depends(get_db),
):
    user_id = read_access_token(credentials.credentials) if credentials else None
    if user_id is None or not ObjectId.is_valid(user_id):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    user = database.users.find_one({"_id": ObjectId(user_id), "status": "active"})
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return user
