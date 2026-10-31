"""Password hashing, JWT issuing/validation, opaque token hashing and rate limits."""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import settings

# Argon2id defaults are OWASP-reasonable; tune up in production hardware.
_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4, hash_len=32, salt_len=16)

MIN_PASSWORD_LENGTH = 10


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, InvalidHashError, ValueError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except (InvalidHashError, ValueError):
        return True


def password_problems(password: str) -> list[str]:
    problems = []
    if len(password) < MIN_PASSWORD_LENGTH:
        problems.append(f"must be at least {MIN_PASSWORD_LENGTH} characters")
    if password.lower() == password:
        problems.append("needs an uppercase letter")
    if password.isalnum():
        problems.append("needs a symbol")
    if password.strip().lower() in {"password123!", "armx12345!", "letmein123!"}:
        problems.append("is too common")
    return problems


def new_opaque_token(prefix: str = "") -> str:
    return f"{prefix}{secrets.token_urlsafe(40)}"


def hash_token(token: str) -> str:
    """Opaque tokens (refresh/reset/pairing) are stored only as SHA-256 hashes."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def constant_time_compare(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


# --------------------------------------------------------------------------
# JWT
# --------------------------------------------------------------------------
def _encode(payload: dict[str, Any]) -> str:
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_access_token(*, user_id: str, role: str, session_id: str) -> str:
    now = datetime.now(timezone.utc)
    return _encode(
        {
            "sub": user_id,
            "role": role,
            "sid": session_id,
            "typ": "access",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=settings.ACCESS_TOKEN_TTL_MINUTES)).timestamp()),
            "jti": secrets.token_hex(8),
        }
    )


@dataclass(slots=True)
class TokenPayload:
    sub: str
    role: str
    sid: str
    typ: str
    exp: int


class TokenError(Exception):
    pass


def decode_token(token: str, *, expected_type: Literal["access"] = "access") -> TokenPayload:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("Token expired") from exc
    except jwt.PyJWTError as exc:
        raise TokenError("Invalid token") from exc
    if payload.get("typ") != expected_type:
        raise TokenError("Wrong token type")
    return TokenPayload(
        sub=payload["sub"], role=payload.get("role", "user"), sid=payload.get("sid", ""), typ=payload["typ"], exp=payload["exp"]
    )


# --------------------------------------------------------------------------
# Approval / action hashing
# --------------------------------------------------------------------------
def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def hash_arguments(args: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(args).encode("utf-8")).hexdigest()


def action_hash(*, tool: str, args: dict[str, Any], actor_id: str, session_id: str, expires_at: datetime) -> str:
    """MEDIUM/HIGH approvals bind tool + args + actor + session + expiry."""
    material = "|".join(
        [tool, hash_arguments(args), actor_id, session_id, str(int(expires_at.timestamp()))]
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------
# Rate limiting (Redis when configured, in-process otherwise)
# --------------------------------------------------------------------------
class InMemoryRateLimiter:
    """Fixed-window counter.

    Process-local by design in single-worker deployments; set REDIS_URL to make
    it shared across workers (the production docker-compose does).
    """

    def __init__(self) -> None:
        self._buckets: dict[str, tuple[int, int]] = {}

    def hit(self, key: str, limit: int, window_seconds: int = 60) -> tuple[bool, int]:
        now = int(time.time())
        window = now // window_seconds
        stored = self._buckets.get(key)
        if stored is None or stored[0] != window:
            self._buckets[key] = (window, 1)
            if len(self._buckets) > 50_000:  # pragma: no cover - defensive
                self._buckets.clear()
            return True, limit - 1
        count = stored[1] + 1
        self._buckets[key] = (window, count)
        return count <= limit, max(0, limit - count)


rate_limiter = InMemoryRateLimiter()
