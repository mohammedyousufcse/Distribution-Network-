"""Application configuration management using environment variables."""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration class loaded from environment and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    APP_NAME: str = "Distribution: Long-Tail Destination Network"
    APP_ENV: str = "development"
    DEBUG: bool = True
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    API_V1_PREFIX: str = "/api/v1"
    DOCS_URL: str = "/docs"
    REDOC_URL: str = "/redoc"
    OPENAPI_URL: str = "/openapi.json"

    # Idempotency cache duration in seconds (defaults to 300 seconds / 5 minutes)
    IDEMPOTENCY_TTL_SECONDS: int = 300

    # Structured logging level (defaults to INFO)
    LOG_LEVEL: str = "INFO"

    # Mastodon Destination Settings
    MASTODON_BASE_URL: str = ""
    MASTODON_ACCESS_TOKEN: str = ""


@lru_cache
def get_settings() -> Settings:
    """Return cached settings instance to avoid reading files repeatedly."""
    return Settings()
