"""Typed, validated application settings.

Everything secret comes from the environment. The process refuses to boot in
production when a required secret is missing or still a placeholder value.
"""

from __future__ import annotations

import base64
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

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
    # APP_BASE_URL takes precedence for absolute links in transactional email.
    WEB_ORIGIN: str = "http://localhost:3000"
    APP_BASE_URL: str = ""
    CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000"

    # --- database ----------------------------------------------------------
    # Local SQLite remains the zero-configuration development default. In
    # production, TURSO_* enables a local embedded replica backed by Turso.
    DATABASE_URL: str = "sqlite+aiosqlite:///./armx.db"
    DB_ECHO: bool = False
    AUTO_CREATE_TABLES: bool = True
    TURSO_DATABASE_URL: str = ""
    TURSO_AUTH_TOKEN: str = ""
    TURSO_REPLICA_PATH: str = "/data/turso-replica.db"
    TURSO_SYNC_INTERVAL_SECONDS: int = Field(default=30, ge=5, le=3600)
    REQUIRE_TURSO_IN_PRODUCTION: bool = False

    # Optional. A single API process has a process-local limiter; Redis is only
    # needed when HTTP traffic is spread over multiple API replicas.
    REDIS_URL: str = ""

    # --- auth --------------------------------------------------------------
    JWT_SECRET: str = "dev-only-insecure-jwt-secret-change-me"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_TTL_MINUTES: int = 15
    REFRESH_TOKEN_TTL_DAYS: int = 30
    SESSION_REFRESH_TTL_HOURS: int = 12  # "remember me" off: short browser session
    PASSWORD_RESET_TTL_MINUTES: int = 15
    EMAIL_VERIFICATION_TTL_HOURS: int = 24
    EMAIL_RESEND_COOLDOWN_SECONDS: int = 60
    LOGIN_MAX_ATTEMPTS: int = 5
    LOGIN_LOCKOUT_MINUTES: int = 15
    REQUIRE_EMAIL_VERIFICATION: bool = False
    CSRF_COOKIE_NAME: str = "armx_csrf"
    ACCESS_COOKIE_NAME: str = "armx_access"
    REFRESH_COOKIE_NAME: str = "armx_refresh"

    # --- secure first-run bootstrap ---------------------------------------
    # Environment seeding is one-shot: it creates an admin only when no admin
    # exists and never rotates an existing password. The protected setup page
    # is the alternative; it requires INITIAL_SETUP_TOKEN.
    FIRST_ADMIN_EMAIL: str = ""
    FIRST_ADMIN_PASSWORD: str = ""
    FIRST_ADMIN_DISPLAY_NAME: str = "Platform owner"
    INITIAL_SETUP_TOKEN: str = ""

    # --- LLM ---------------------------------------------------------------
    # "groq" is the production default. Provider/model rows in the database
    # take precedence and are balanced within a priority tier with failover.
    LLM_PROVIDER: str = "groq"
    LLM_ROUTING_STRATEGY: Literal["balanced", "priority"] = "balanced"
    LLM_SECRETS_KEY: str = ""
    LLM_MAX_TOKENS: int = 4096
    # Bound both one provider attempt and the full failover path so an
    # interactive chat can never wait through N sequential HTTP timeouts.
    LLM_TIMEOUT_SECONDS: float = Field(default=25.0, ge=3.0, le=300.0)
    LLM_ROUTE_TIMEOUT_SECONDS: float = Field(default=45.0, ge=5.0, le=300.0)
    ASSISTANT_REQUEST_TIMEOUT_SECONDS: float = Field(default=50.0, ge=10.0, le=330.0)
    LLM_FAILURE_THRESHOLD: int = Field(default=3, ge=1, le=20)
    LLM_CIRCUIT_COOLDOWN_SECONDS: int = Field(default=60, ge=10, le=3600)
    HARNESS_MAX_STEPS: int = 8

    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.3-70b-versatile"
    GROQ_BASE_URL: str = "https://api.groq.com/openai/v1"
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_API_KEYS: str = ""  # comma separated pool of the owner's own keys
    ANTHROPIC_MODEL: str = "claude-sonnet-4-5-20250929"
    ANTHROPIC_BASE_URL: str = "https://api.anthropic.com"
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"

    # --- transactional email: Resend REST API only -------------------------
    # SMTP is intentionally not used for authentication email. All secrets stay
    # server-side; the frontend only sees capability flags, never these values.
    RESEND_API_KEY: str = ""
    RESEND_FROM_EMAIL: str = ""
    RESEND_WEBHOOK_SECRET: str = ""
    RESEND_API_URL: str = "https://api.resend.com/emails"
    RESEND_MAX_ATTEMPTS: int = 3
    RESEND_TIMEOUT_SECONDS: float = 10.0

    # Legacy SMTP_* values are accepted but unused; kept so an existing Render
    # environment does not fail on unknown variables (BaseSettings ignores extra).
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
    WHATSAPP_TOKEN: str = ""  # Meta Graph API access token (outbound)
    WHATSAPP_PHONE_ID: str = ""
    # Inbound webhook secrets are intentionally separate from the access token.
    WHATSAPP_VERIFY_TOKEN: str = ""
    WHATSAPP_APP_SECRET: str = ""
    WHATSAPP_WEBHOOK_MAX_BYTES: int = Field(default=1_048_576, ge=1024, le=8_388_608)
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
    def turso_enabled(self) -> bool:
        return bool(self.TURSO_DATABASE_URL and self.TURSO_AUTH_TOKEN)

    @property
    def effective_database_url(self) -> str:
        if not self.turso_enabled:
            return self.DATABASE_URL
        path = str(Path(self.TURSO_REPLICA_PATH).expanduser())
        return f"sqlite+aioturso_sync:///{path}"

    @property
    def database_connect_args(self) -> dict[str, Any]:
        if not self.turso_enabled:
            return {}
        return {
            "remote_url": self.TURSO_DATABASE_URL,
            "auth_token": self.TURSO_AUTH_TOKEN,
            "client_name": "armx-render",
            "bootstrap_if_empty": True,
            "long_poll_timeout_ms": 1000,
        }

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def auth_base_url(self) -> str:
        """Absolute public origin for recovery/verification links."""
        return (self.APP_BASE_URL or self.WEB_ORIGIN).rstrip("/")

    @property
    def resend_configured(self) -> bool:
        return bool(self.RESEND_API_KEY and self.RESEND_FROM_EMAIL)

    @property
    def anthropic_key_pool(self) -> list[str]:
        keys = [k.strip() for k in self.ANTHROPIC_API_KEYS.split(",") if k.strip()]
        if self.ANTHROPIC_API_KEY and self.ANTHROPIC_API_KEY not in keys:
            keys.insert(0, self.ANTHROPIC_API_KEY)
        return keys

    @property
    def allowed_entities(self) -> set[str]:
        return {
            e.strip()
            for e in self.HOME_ASSISTANT_ALLOWED_ENTITIES.split(",")
            if e.strip()
        }

    @property
    def github_target_allowlist(self) -> list[str]:
        return [
            t.strip().lower()
            for t in self.GITHUB_ALLOWED_TARGETS.split(",")
            if t.strip()
        ]

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
        """Reject partial integrations and unsafe production configuration."""
        if bool(self.TURSO_DATABASE_URL) != bool(self.TURSO_AUTH_TOKEN):
            raise RuntimeError(
                "Set both TURSO_DATABASE_URL and TURSO_AUTH_TOKEN, or neither"
            )
        if self.TURSO_DATABASE_URL and not self.TURSO_DATABASE_URL.startswith(
            ("https://", "libsql://", "turso://")
        ):
            raise RuntimeError(
                "TURSO_DATABASE_URL must use https://, libsql://, or turso://"
            )
        if bool(self.FIRST_ADMIN_EMAIL) != bool(self.FIRST_ADMIN_PASSWORD):
            raise RuntimeError(
                "Set both FIRST_ADMIN_EMAIL and FIRST_ADMIN_PASSWORD, or neither"
            )
        if self.FIRST_ADMIN_PASSWORD:
            password = self.FIRST_ADMIN_PASSWORD
            if len(password) < 10 or password.lower() == password or password.isalnum():
                raise RuntimeError(
                    "FIRST_ADMIN_PASSWORD must be at least 10 characters with an uppercase letter and symbol"
                )
        if self.INITIAL_SETUP_TOKEN and len(self.INITIAL_SETUP_TOKEN) < 32:
            raise RuntimeError("INITIAL_SETUP_TOKEN must be at least 32 characters")
        if self.LLM_SECRETS_KEY:
            try:
                decoded = base64.urlsafe_b64decode(self.LLM_SECRETS_KEY.encode("ascii"))
            except Exception as exc:
                raise RuntimeError(
                    "LLM_SECRETS_KEY must be a URL-safe base64 key"
                ) from exc
            if len(decoded) != 32:
                raise RuntimeError("LLM_SECRETS_KEY must decode to exactly 32 bytes")

        if not self.is_production:
            return self

        required = {
            "JWT_SECRET": self.JWT_SECRET,
            "DATABASE": self.effective_database_url,
            "LLM_SECRETS_KEY": self.LLM_SECRETS_KEY,
            "RESEND_API_KEY": self.RESEND_API_KEY,
            "RESEND_FROM_EMAIL": self.RESEND_FROM_EMAIL,
        }
        if not self.auth_base_url.startswith("https://"):
            raise RuntimeError(
                "APP_BASE_URL (or WEB_ORIGIN) must be an absolute https:// URL in production"
            )
        if self.REQUIRE_TURSO_IN_PRODUCTION and not self.turso_enabled:
            raise RuntimeError(
                "Turso is required: set TURSO_DATABASE_URL and TURSO_AUTH_TOKEN"
            )
        if self.AUTO_CREATE_TABLES:
            raise RuntimeError(
                "AUTO_CREATE_TABLES must be false in production; run alembic upgrade head"
            )
        if self.DEBUG:
            raise RuntimeError("DEBUG must be false in production")

        problems = []
        for name, value in required.items():
            if value.strip().lower() in PLACEHOLDERS or len(value) < 16:
                problems.append(name)
        if problems:
            raise RuntimeError(
                "Refusing to boot in production with missing/placeholder secrets: "
                + ", ".join(problems)
            )
        if len(self.JWT_SECRET) < 32:
            raise RuntimeError(
                "JWT_SECRET must be at least 32 characters in production"
            )
        if not self.WEB_ORIGIN.startswith("https://"):
            raise RuntimeError("WEB_ORIGIN must be https in production")
        if self.turso_enabled and not Path(self.TURSO_REPLICA_PATH).is_absolute():
            raise RuntimeError("TURSO_REPLICA_PATH must be absolute in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

# Make the settings visible to libraries that read os.environ directly.
os.environ.setdefault("ARMX_ENV", settings.ENV)
