from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from pymongo.errors import ServerSelectionTimeoutError

from app.main import app


def test_health_returns_ok() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_frontend_is_available() -> None:
    with TestClient(app) as client:
        response = client.get("/")
        script = client.get("/static/app.js")

    assert response.status_code == 200
    assert "问卷工作台" in response.text
    assert script.status_code == 200
    assert "loadSharedSurvey" in script.text


def test_health_db_returns_ok_when_ping_succeeds() -> None:
    with patch("app.db.mongo.create_mongo_client") as create_client:
        database = Mock()
        database.command.return_value = {"ok": 1}
        mongo_client = Mock()
        mongo_client.__getitem__ = Mock(return_value=database)
        create_client.return_value = mongo_client

        with TestClient(app) as client:
            response = client.get("/health/db")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "connected"}
    database.command.assert_called_once_with("ping")


def test_health_db_returns_503_when_ping_fails() -> None:
    with patch("app.db.mongo.create_mongo_client") as create_client:
        database = Mock()
        database.command.side_effect = ServerSelectionTimeoutError("timeout")
        mongo_client = Mock()
        mongo_client.__getitem__ = Mock(return_value=database)
        create_client.return_value = mongo_client

        with TestClient(app) as client:
            response = client.get("/health/db")

    assert response.status_code == 503
    assert response.json() == {"detail": "MongoDB connection failed"}
