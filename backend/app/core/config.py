"""Typed, validated application settings.

Everything secret comes from the environment. The process refuses to boot in
production when a required secret is missing or still a placeholder value.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PLACEHOLDERS = {
    "",
    "changeme",
    "change-me",
    "replace-me",
    "your-key-here",
    "sk-ant-xxx",
    "secret",
    "todo",
    "xxx",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"), env_file_encoding="utf-8", extra="ignore"
    )

    # --- runtime -----------------------------------------------------------
    APP_NAME: str = "A.R.M.X AI"
    ENV: Literal["development", "staging", "production", "test"] = "development"
    DEBUG: bool = False
    API_PREFIX: str = "/api"
    LOG_LEVEL: str = "INFO"

    # Public origin of the web app (used for reset links + CORS).
    WEB_ORIGIN: str = "http://localhost:3000"
    CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"

    # --- database ----------------------------------------------------------
    DATABASE_URL: str = "sqlite+aiosqlite:///./armx.db"
    DB_ECHO: bool = False
    AUTO_CREATE_TABLES: bool = True

    REDIS_URL: str = ""

    # --- auth --------------------------------------------------------------
    JWT_SECRET: str = "dev-only-insecure-jwt-secret-change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_TTL_MINUTES: int = 15
    REFRESH_TOKEN_TTL_DAYS: int = 30
    PASSWORD_RESET_TTL_MINUTES: int = 20
    LOGIN_MAX_ATTEMPTS: int = 5
    LOGIN_LOCKOUT_MINUTES: int = 15
    REQUIRE_EMAIL_VERIFICATION: bool = False

    # --- bootstrap of the first admin (CLI only) ---------------------------
    FIRST_ADMIN_EMAIL: str = ""
    FIRST_ADMIN_PASSWORD: str = ""

    # --- LLM ---------------------------------------------------------------
    LLM_PROVIDER: Literal["claude", "openai", "mock"] = "mock"
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_API_KEYS: str = ""  # comma separated pool of the owner's own keys
    ANTHROPIC_MODEL: str = "claude-sonnet-4-5-20250929"
    ANTHROPIC_BASE_URL: str = "https://api.anthropic.com"
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    LLM_MAX_TOKENS: int = 2048
    LLM_TIMEOUT_SECONDS: float = 60.0
    HARNESS_MAX_STEPS: int = 8

    # --- email -------------------------------------------------------------
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "no-reply@armx.local"
    SMTP_TLS: bool = True

    # --- google oauth ------------------------------------------------------
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/auth/google/callback"

    # --- home assistant ----------------------------------------------------
    HOME_ASSISTANT_URL: str = ""
    HOME_ASSISTANT_TOKEN: str = ""
    HOME_ASSISTANT_ALLOWED_ENTITIES: str = "light.living_room,light.desk,switch.fan"
    MQTT_HOST: str = ""
    MQTT_PORT: int = 8883
    MQTT_USERNAME: str = ""
    MQTT_PASSWORD: str = ""
    MQTT_TLS: bool = True

    # --- search ------------------------------------------------------------
    SEARCH_PROVIDER: Literal["google", "bing", "none"] = "none"
    GOOGLE_SEARCH_API_KEY: str = ""
    GOOGLE_SEARCH_CX: str = ""
    BING_SEARCH_API_KEY: str = ""

    # --- github / vercel / turso (build pipeline) --------------------------
    GITHUB_TOKEN: str = ""
    GITHUB_DEFAULT_ORG: str = ""
    GITHUB_ALLOWED_TARGETS: str = ""  # comma separated owner/repo prefixes
    VERCEL_TOKEN: str = ""
    VERCEL_TEAM_ID: str = ""
    VERCEL_ALLOWED_PROJECT_PREFIX: str = "armx-"
    TURSO_API_TOKEN: str = ""
    TURSO_ORG: str = ""
    TURSO_BASE_URL: str = "https://api.turso.tech"
    PIPELINE_MODE: Literal["live", "simulated"] = "simulated"
    PROJECT_WORKSPACE: str = "./var/workspace"

    # --- messaging ---------------------------------------------------------
    WHATSAPP_TOKEN: str = ""
    WHATSAPP_PHONE_ID: str = ""
    MESSENGER_TOKEN: str = ""
    MESSENGER_PAGE_ID: str = ""
    MESSAGING_MODE: Literal["live", "simulated"] = "simulated"

    # --- mail reading ------------------------------------------------------
    IMAP_HOST: str = ""
    IMAP_PORT: int = 993
    IMAP_USER: str = ""
    IMAP_PASSWORD: str = ""

    # --- policy ------------------------------------------------------------
    TOOL_RATE_LIMIT_PER_MINUTE: int = 30
    APPROVAL_TTL_SECONDS: int = 120
    MAX_UPLOAD_BYTES: int = 8 * 1024 * 1024

    # ----------------------------------------------------------------------
    @property
    def is_production(self) -> bool:
        return self.ENV == "production"

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def anthropic_key_pool(self) -> list[str]:
        keys = [k.strip() for k in self.ANTHROPIC_API_KEYS.split(",") if k.strip()]
        if self.ANTHROPIC_API_KEY and self.ANTHROPIC_API_KEY not in keys:
            keys.insert(0, self.ANTHROPIC_API_KEY)
        return keys

    @property
    def allowed_entities(self) -> set[str]:
        return {e.strip() for e in self.HOME_ASSISTANT_ALLOWED_ENTITIES.split(",") if e.strip()}

    @property
    def github_target_allowlist(self) -> list[str]:
        return [t.strip().lower() for t in self.GITHUB_ALLOWED_TARGETS.split(",") if t.strip()]

    @field_validator("DATABASE_URL")
    @classmethod
    def _normalise_db_url(cls, v: str) -> str:
        if v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql+asyncpg://", 1)
        if v.startswith("postgresql://") and "+asyncpg" not in v:
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    @model_validator(mode="after")
    def _production_guards(self) -> "Settings":
        """Refuse to boot in production with a missing or placeholder secret."""
        if not self.is_production:
            return self

        required = {
            "JWT_SECRET": self.JWT_SECRET,
            "DATABASE_URL": self.DATABASE_URL,
        }
        if self.LLM_PROVIDER == "claude":
            required["ANTHROPIC_API_KEY/ANTHROPIC_API_KEYS"] = self.ANTHROPIC_API_KEY or self.ANTHROPIC_API_KEYS
        if self.LLM_PROVIDER == "openai":
            required["OPENAI_API_KEY"] = self.OPENAI_API_KEY
        if self.AUTO_CREATE_TABLES:
            raise RuntimeError("AUTO_CREATE_TABLES must be false in production; run alembic upgrade head")
        if self.DEBUG:
            raise RuntimeError("DEBUG must be false in production")

        problems = []
        for name, value in required.items():
            if value.strip().lower() in PLACEHOLDERS or len(value) < 16:
                problems.append(name)
        if problems:
            raise RuntimeError(
                "Refusing to boot in production with missing/placeholder secrets: " + ", ".join(problems)
            )
        if not self.WEB_ORIGIN.startswith("https://"):
            raise RuntimeError("WEB_ORIGIN must be https in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

# Make the settings visible to libraries that read os.environ directly.
os.environ.setdefault("ARMX_ENV", settings.ENV)
