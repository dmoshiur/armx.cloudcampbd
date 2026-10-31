"""FastAPI dependencies: current user, role gates, request context."""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.security import TokenError, decode_token
from app.models import Role, Session, User

bearer = HTTPBearer(auto_error=False)

ROLE_RANK = {Role.USER.value: 1, Role.VIP.value: 2, Role.ADMIN.value: 3}


@dataclass(slots=True)
class AuthContext:
    user: User
    session: Session
    token_jti: str = ""


def _unauthorized(detail: str = "Not authenticated") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_auth_context(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: AsyncSession = Depends(get_db),
) -> AuthContext:
    if creds is None or not creds.credentials:
        raise _unauthorized()
    try:
        payload = decode_token(creds.credentials, expected_type="access")
    except TokenError as exc:
        raise _unauthorized(str(exc)) from exc

    user = await db.get(User, payload.sub)
    if user is None or not user.is_active:
        raise _unauthorized("Account is inactive")

    session = await db.get(Session, payload.sid)
    from datetime import datetime, timezone

    from app.core.db import as_utc

    if (
        session is None
        or session.revoked_at is not None
        or as_utc(session.expires_at) < datetime.now(timezone.utc)
    ):
        raise _unauthorized("Session is no longer valid")

    # Real accounts must be verified before any authenticated use.
    from app.core.config import settings

    if settings.REQUIRE_EMAIL_VERIFICATION and user.google_sub is None and not user.is_verified:
        raise HTTPException(status_code=403, detail="Email not verified")

    return AuthContext(user=user, session=session)


async def get_current_user(ctx: AuthContext = Depends(get_auth_context)) -> User:
    return ctx.user


def require_role(minimum: str):
    need = ROLE_RANK[minimum]

    async def _dep(ctx: AuthContext = Depends(get_auth_context)) -> User:
        if ROLE_RANK.get(ctx.user.role, 0) < need:
            raise HTTPException(status_code=403, detail=f"Requires {minimum} role")
        return ctx.user

    return _dep


async def require_admin(user: User = Depends(require_role(Role.ADMIN.value))) -> User:
    return user


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


def user_agent(request: Request) -> str:
    return request.headers.get("user-agent", "")[:400]
