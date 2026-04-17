from typing import Optional

from pydantic_settings import BaseSettings
from pydantic import Field
from pathlib import Path
from zoneinfo import ZoneInfo
ROOT_DIR = Path(__file__).resolve().parents[3]  


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
    GOOGLE_FORMS_WEBHOOK_URL :Optional[str] = Field(default=None, env="GOOGLE_FORMS_WEBHOOK_URL")
    CONFIG_SERVICE_URL: Optional[str] = Field(default=None, env="CONFIG_SERVICE_URL")
    CONFIG_SERVICE_TOKEN: Optional[str] = Field(default=None, env="CONFIG_SERVICE_TOKEN")
    EMAIL_SERVICE_URL: Optional[str] = Field(default=None, env="EMAIL_SERVICE_URL")
    FRONTEND_BASE_URL: Optional[str] = Field(default=None, env="FRONTEND_BASE_URL")
    AUTH_TOKEN_URL: str = Field(default="/authentication/api/v1/auth/token", env="AUTH_TOKEN_URL")

    class Config:
        env_file=ROOT_DIR / ".env",
        env_file_encoding = "utf-8"

settings = Settings()
APP_TZ = ZoneInfo(settings.app_timezone)
