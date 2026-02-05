from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    ROOT_PATH: str = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-secret-key-change-me")
    SQLALCHEMY_DATABASE_URI: str = os.getenv("DATABASE_URL", "sqlite:///app.db")
    REMEMBER_COOKIE_DURATION: timedelta = timedelta(days=14)
    APP_NAME: str = os.getenv("APP_NAME", "app")
    APP_VERSION: str = os.getenv("APP_VERSION", "0.0.1")
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 1 week
    AUTH_COOKIE_NAME: str = "access_token"
    ALLOWED_EXTENSIONS: set[str] = ("png", "jpg", "jpeg", "webp")
    MAX_CONTENT_LENGTH: int = 4 * 1024 * 1024
    AUTHOR: str = "JRO"
    ALLOWED_IMAGE_EXTS: set[str] = ("png", "jpg", "jpeg", "webp")
    SESSION_COOKIE_SAMESITE: str = "Lax"
    SESSION_COOKIE_SECURE: bool = False


settings = Settings()
