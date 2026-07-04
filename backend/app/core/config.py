from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/tomato_agent"
    jwt_secret_key: str = "dev-only-change-me-with-at-least-32-bytes"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7
    openai_api_key: str | None = None
    openai_text_model: str = "gpt-4.1-mini"
    openai_vision_model: str = "gpt-4.1-mini"
    weather_api_key: str | None = None
    cors_origins: str = (
        "http://localhost:5174,http://127.0.0.1:5174,"
        "http://localhost:8000,http://127.0.0.1:8000"
    )
    public_base_url: str = "http://127.0.0.1:8000"
    frontend_base_url: str = "http://127.0.0.1:5174"
    google_client_id: str | None = None
    google_client_secret: str | None = None
    github_client_id: str | None = None
    github_client_secret: str | None = None

    model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
