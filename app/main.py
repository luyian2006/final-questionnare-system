from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pymongo.errors import PyMongoError

from app.api import router
from app.db.mongo import close_mongo_client, ensure_indexes, get_database, ping_database
from app.question_api import router as question_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    database = get_database(app)
    try:
        ensure_indexes(database)
        app.state.mongo_indexes_ready = True
    except PyMongoError:
        # Keep the process and the database-independent health endpoint usable
        # while MongoDB is starting or temporarily unavailable.  Database-backed
        # endpoints will still fail normally, and /health/db retries setup.
        app.state.mongo_indexes_ready = False
    try:
        yield
    finally:
        close_mongo_client(app)


app = FastAPI(
    title="Survey System",
    description="MongoDB-backed questionnaire system.",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(router)
app.include_router(question_router)


FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/", include_in_schema=False)
def frontend() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/db")
def health_db() -> dict[str, str]:
    try:
        ping_database(app)
        if not getattr(app.state, "mongo_indexes_ready", False):
            ensure_indexes(get_database(app))
            app.state.mongo_indexes_ready = True
    except PyMongoError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MongoDB connection failed",
        )
    return {"status": "ok", "database": "connected"}
