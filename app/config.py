from __future__ import annotations

from functools import lru_cache
from typing import Set

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = Field(default="development", alias="APP_ENV")
    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")
    base_url: str = Field(default="http://localhost:8000", alias="BASE_URL")
    internal_api_token: str = Field(alias="INTERNAL_API_TOKEN")

    database_url: str = Field(alias="DATABASE_URL")
    redis_url: str = Field(alias="REDIS_URL")

    slack_bot_token: str = Field(alias="SLACK_BOT_TOKEN")
    slack_app_token: str = Field(default="", alias="SLACK_APP_TOKEN")
    slack_signing_secret: str = Field(alias="SLACK_SIGNING_SECRET")
    slack_use_socket_mode: bool = Field(default=False, alias="SLACK_USE_SOCKET_MODE")
    slack_team_id: str = Field(default="", alias="SLACK_TEAM_ID")
    slack_allowed_approver_ids: str = Field(default="", alias="SLACK_ALLOWED_APPROVER_IDS")
    slack_default_channel_id: str = Field(default="", alias="SLACK_DEFAULT_CHANNEL_ID")

    approval_ttl_seconds: int = Field(default=600, alias="APPROVAL_TTL_SECONDS")
    redis_lock_ttl_seconds: int = Field(default=10, alias="REDIS_LOCK_TTL_SECONDS")
    expiration_sweep_seconds: int = Field(default=15, alias="EXPIRATION_SWEEP_SECONDS")

    @property
    def allowed_approver_ids(self) -> Set[str]:
        return {
            user_id.strip()
            for user_id in self.slack_allowed_approver_ids.split(",")
            if user_id.strip()
        }

    @property
    def has_placeholder_signing_secret(self) -> bool:
        return self.slack_signing_secret in {"replace-me", "REPLACE_WITH_SLACK_SIGNING_SECRET", ""}

    @property
    def socket_mode_enabled(self) -> bool:
        return self.slack_use_socket_mode

    @property
    def has_socket_mode_token(self) -> bool:
        return bool(self.slack_app_token.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
