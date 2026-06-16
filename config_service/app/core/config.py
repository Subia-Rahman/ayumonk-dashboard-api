from __future__ import annotations
from pydantic_settings import BaseSettings
from pydantic import Field
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Optional
ROOT_DIR = Path(__file__).resolve().parents[3]  # project root


class Settings(BaseSettings):
    SQLALCHEMY_DATABASE_URI: str = Field(..., env="SQLALCHEMY_DATABASE_URI")
    SERVICE_NAME: str = "config-service"

    mysql_root_password: str = Field(..., env="mysql_root_password")
    mysql_database: str = Field(..., env="mysql_database")
    app_timezone: str = Field("UTC", env="APP_TIMEZONE")
    GOOGLE_FORMS_CREDENTIALS_FILE: Optional[str] = Field(default=None, env="GOOGLE_FORMS_CREDENTIALS_FILE")
    GOOGLE_FORMS_DELEGATED_USER: Optional[str] = Field(default=None, env="GOOGLE_FORMS_DELEGATED_USER")
    GOOGLE_FORMS_TITLE_PREFIX: str = Field(default="Session", env="GOOGLE_FORMS_TITLE_PREFIX")
    GOOGLE_FORMS_CLIENT_ID: Optional[str] = Field(default=None, env="GOOGLE_FORMS_CLIENT_ID")
    GOOGLE_FORMS_CLIENT_SECRET: Optional[str] = Field(default=None, env="GOOGLE_FORMS_CLIENT_SECRET")
    GOOGLE_FORMS_REFRESH_TOKEN: Optional[str] = Field(default=None, env="GOOGLE_FORMS_REFRESH_TOKEN")
    GOOGLE_FORMS_TOKEN_URI: str = Field(
        default="https://oauth2.googleapis.com/token",
        env="GOOGLE_FORMS_TOKEN_URI",
    )
    GOOGLE_FORMS_WEBHOOK_URL: Optional[str] = Field(default=None, env="GOOGLE_FORMS_WEBHOOK_URL")
    GOOGLE_FORMS_EMAIL_QUESTION_TITLE: str = Field(default="Email", env="GOOGLE_FORMS_EMAIL_QUESTION_TITLE")
    EMPLOYEE_FORM_WEBHOOK_SECRET: Optional[str] = Field(default=None, env="EMPLOYEE_FORM_WEBHOOK_SECRET")
    FRONTEND_BASE_URL: Optional[str] = Field(default=None, env="FRONTEND_BASE_URL")
    SESSION_FORM_PREVIEW_PATH: str = Field(
        default="/sessions/{session_id}/preview",
        env="SESSION_FORM_PREVIEW_PATH",
    )
    SESSION_FORM_PATH: str = Field(
        default="/sessions/{session_id}/form",
        env="SESSION_FORM_PATH",
    )
    EMAIL_SERVICE_URL: Optional[str] = Field(default=None, env="EMAIL_SERVICE_URL")
    EMAIL_SEND_ON_PUBLISH: bool = Field(default=True, env="EMAIL_SEND_ON_PUBLISH")
    EMAIL_SEND_BATCH_SIZE: int = Field(default=50, env="EMAIL_SEND_BATCH_SIZE")
    EMAIL_SEND_TIMEOUT_SECONDS: float = Field(default=10.0, env="EMAIL_SEND_TIMEOUT_SECONDS")
    # When False (default) the EmailClient calls email_service's smtp_client
    # directly via asyncio.to_thread, skipping a same-process HTTP loopback.
    # Flip to True only when email_service runs as a separate deployable.
    EMAIL_USE_HTTP_TRANSPORT: bool = Field(default=False, env="EMAIL_USE_HTTP_TRANSPORT")
    # Concurrency cap for the per-minute reminder dispatcher. Each in-flight
    # task holds one DB session, so this is bounded by the DB pool size below.
    REMINDER_DISPATCH_CONCURRENCY: int = Field(default=8, env="REMINDER_DISPATCH_CONCURRENCY")
    # SQLAlchemy async pool tuning. Defaults are larger than SQLAlchemy's
    # built-ins so the dispatcher's concurrent fan-out doesn't starve API
    # requests of connections.
    DB_POOL_SIZE: int = Field(default=20, env="DB_POOL_SIZE")
    DB_MAX_OVERFLOW: int = Field(default=20, env="DB_MAX_OVERFLOW")
    DB_POOL_RECYCLE_SECONDS: int = Field(default=1800, env="DB_POOL_RECYCLE_SECONDS")
    EMAIL_PUBLISH_SUBJECT_TEMPLATE: str = Field(
        default="New Session Form: {session_title}",
        env="EMAIL_PUBLISH_SUBJECT_TEMPLATE",
    )
    EMAIL_PUBLISH_BODY_TEMPLATE: str = Field(
        default=(
            "Hello,\n\n"
            "A new session form has been published: {session_title}\n"
            "Please submit your response here:\n{form_url}\n\n"
            "Thank you."
        ),
        env="EMAIL_PUBLISH_BODY_TEMPLATE",
    )
    ADMIN_WELCOME_SUBJECT_TEMPLATE: str = Field(
        default="Your Admin Account Credentials",
        env="ADMIN_WELCOME_SUBJECT_TEMPLATE",
    )
    ADMIN_WELCOME_BODY_TEMPLATE: str = Field(
        default=(
            "Hello,\n\n"
            "Your admin account has been created.\n"
            "Username: {username}\n"
            "Password: {password}\n"
            "Email: {email}\n\n"
            "Please login and change your password after first login."
        ),
        env="ADMIN_WELCOME_BODY_TEMPLATE",
    )
    CONFIG_SERVICE_URL: Optional[str] = Field(default=None, env="CONFIG_SERVICE_URL")
    CONFIG_SERVICE_TOKEN: Optional[str] = Field(default=None, env="CONFIG_SERVICE_TOKEN")
    EMAIL_SERVICE_URL: Optional[str] = Field(default=None, env="EMAIL_SERVICE_URL")
    FRONTEND_BASE_URL: Optional[str] = Field(default=None, env="FRONTEND_BASE_URL")
    AUTH_TOKEN_URL: str = Field(default="/authentication/api/v1/auth/login", env="AUTH_TOKEN_URL")
    DEBUG_ERRORS: bool = Field(default=False, env="DEBUG_ERRORS")
    VAPID_PRIVATE_KEY:Optional[str] = Field(default=None, env="VAPID_PRIVATE_KEY")
    VAPID_EMAIL:Optional[str] = Field(default=None, env="VAPID_EMAIL")

    class Config:
        env_file=ROOT_DIR / ".env",
        env_file_encoding = "utf-8"

settings = Settings()
APP_TZ = ZoneInfo(settings.app_timezone)
