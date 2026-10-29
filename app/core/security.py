"""Small standard-library password and bearer-token helpers."""

import base64
import hashlib
import hmac
import json
import secrets
import time

from app.core.config import settings


PBKDF2_ITERATIONS = 310_000


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${_b64encode(salt)}${_b64encode(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, salt_text, digest_text = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        expected = _b64decode(digest_text)
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), _b64decode(salt_text), int(iterations)
        )
        return hmac.compare_digest(actual, expected)
    except (AttributeError, TypeError, ValueError):
        return False


def create_access_token(user_id: str) -> str:
    payload = _b64encode(
        json.dumps(
            {"sub": user_id, "exp": int(time.time()) + settings.access_token_ttl_seconds},
            separators=(",", ":"),
        ).encode("utf-8")
    )
    signature = hmac.new(settings.auth_secret.encode(), payload.encode(), hashlib.sha256).digest()
    return f"{payload}.{_b64encode(signature)}"


def read_access_token(token: str) -> str | None:
    try:
        payload, signature = token.split(".", 1)
        expected = hmac.new(settings.auth_secret.encode(), payload.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _b64decode(signature)):
            return None
        claims = json.loads(_b64decode(payload))
        if not isinstance(claims.get("sub"), str) or claims.get("exp", 0) <= time.time():
            return None
        return claims["sub"]
    except (AttributeError, TypeError, ValueError, json.JSONDecodeError):
        return None
