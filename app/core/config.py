import os
from dataclasses import dataclass

from dotenv import load_dotenv


load_dotenv()


@dataclass(frozen=True)
class Settings:
    mongodb_uri: str = os.getenv("MONGODB_URI", "mongodb://127.0.0.1:27017")
    mongodb_database: str = os.getenv("MONGODB_DATABASE", "survey_system")
    auth_secret: str = os.getenv("AUTH_SECRET", "development-only-change-me")
    access_token_ttl_seconds: int = int(os.getenv("ACCESS_TOKEN_TTL_SECONDS", "43200"))


settings = Settings()
