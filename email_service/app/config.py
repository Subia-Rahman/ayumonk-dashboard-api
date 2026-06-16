from __future__ import annotations
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]
APP_DIR = Path(__file__).resolve().parents[1]

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=APP_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    SMTP_HOST: str | None = None
    SMTP_PORT: int | None = None
    SMTP_USER: str | None = None
    SMTP_PASS: str | None = None
    SMTP_USE_TLS: bool = True
    SMTP_USE_SSL: bool = False
    FROM_EMAIL: str | None = None
    EMAIL_CONFIG_CACHE_SECONDS: int = 60
    EMAIL_SEND_MAX_RETRIES: int = 2
    EMAIL_SEND_RETRY_DELAY_SECONDS: float = 1.0
    # Per-attempt SMTP socket timeout. Was hardcoded at 20s before, which
    # combined with retries meant up to 60s of blocking per email. 10s is
    # more than enough for a reachable SMTP relay.
    SMTP_TIMEOUT_SECONDS: float = 10.0

settings = Settings()
