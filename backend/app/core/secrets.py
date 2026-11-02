"""Encryption-at-rest for administrator-managed provider credentials."""
from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


class SecretConfigurationError(RuntimeError):
    pass


def _fernet() -> Fernet:
    if not settings.LLM_SECRETS_KEY:
        raise SecretConfigurationError(
            "LLM_SECRETS_KEY is not configured; provider credentials cannot be stored"
        )
    try:
        return Fernet(settings.LLM_SECRETS_KEY.encode("ascii"))
    except (ValueError, TypeError) as exc:
        raise SecretConfigurationError("LLM_SECRETS_KEY is invalid") from exc


def encrypt_secret(value: str) -> str:
    if not value:
        return ""
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str) -> str:
    if not value:
        return ""
    try:
        return _fernet().decrypt(value.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise SecretConfigurationError(
            "Stored provider credential cannot be decrypted with the configured LLM_SECRETS_KEY"
        ) from exc


def secret_hint(value: str) -> str:
    if not value:
        return "not set"
    if len(value) <= 8:
        return "configured"
    return f"••••{value[-4:]}"
