"""Authentication: email/password, rotating refresh tokens, reset, Google OIDC.

Refresh tokens are opaque, stored only as SHA-256 hashes, rotate on every use, and
reuse of an already-rotated token revokes the whole session family (token theft
detection).
"""
from __future__ import annotations

import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import audit
from app.core.config import settings
from app.core.db import as_utc, get_db
from app.core.deps import AuthContext, get_auth_context, get_current_user, client_ip, user_agent
from app.core.mailer import send_password_reset, send_verification
from app.core.security import (
    create_access_token,
    hash_password,
    hash_token,
    new_opaque_token,
    password_needs_rehash,
    rate_limiter,
    verify_password,
)
from app.models import EmailVerificationToken, PasswordResetToken, Role, Session, User
from app.schemas.auth import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    RefreshRequest,
    ResetPasswordRequest,
    SignupRequest,
    TokenPair,
    UserOut,
)

router = APIRouter(prefix="/auth", tags=["auth"])


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
async def _issue_tokens(db: AsyncSession, user: User, request: Request, *, rotated_from: str | None = None) -> TokenPair:
    refresh = new_opaque_token("rt_")
    session = Session(
        user_id=user.id,
        refresh_token_hash=hash_token(refresh),
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_TTL_DAYS),
        rotated_from=rotated_from,
        user_agent=user_agent(request),
        ip_address=client_ip(request),
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return TokenPair(
        access_token=create_access_token(user_id=user.id, role=user.role, session_id=session.id),
        refresh_token=refresh,
        expires_in=settings.ACCESS_TOKEN_TTL_MINUTES * 60,
    )


def _check_auth_rate_limit(request: Request, bucket: str, limit: int = 10) -> None:
    key = f"auth:{bucket}:{client_ip(request)}"
    ok, _ = rate_limiter.hit(key, limit)
    if not ok:
        raise HTTPException(status_code=429, detail="Too many attempts. Try again in a minute.")


def _locked(user: User) -> bool:
    if user.locked_until is None:
        return False
    return as_utc(user.locked_until) > datetime.now(timezone.utc)


async def _register_failed_login(db: AsyncSession, user: User) -> None:
    user.failed_login_count += 1
    if user.failed_login_count >= settings.LOGIN_MAX_ATTEMPTS:
        user.locked_until = datetime.now(timezone.utc) + timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES)
        user.failed_login_count = 0
    await db.commit()


async def _reset_failed_login(db: AsyncSession, user: User) -> None:
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()


# --------------------------------------------------------------------------
# signup / login
# --------------------------------------------------------------------------
@router.post("/signup", response_model=TokenPair, status_code=201)
async def signup(
    payload: SignupRequest, request: Request, db: AsyncSession = Depends(get_db)
) -> TokenPair:
    _check_auth_rate_limit(request, "signup", limit=5)
    email = payload.email.lower().strip()
    existing = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if existing is not None:
        # Do not leak account existence; behave like success but do nothing.
        raise HTTPException(status_code=409, detail="Could not create the account with those details")

    # Public signup can only create role=user. The first admin comes from the CLI.
    user = User(
        email=email,
        display_name=payload.display_name.strip() or email.split("@")[0][:60],
        password_hash=hash_password(payload.password),
        role=Role.USER.value,
        is_verified=not settings.REQUIRE_EMAIL_VERIFICATION,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    if settings.REQUIRE_EMAIL_VERIFICATION:
        raw = new_opaque_token("ev_")
        db.add(
            EmailVerificationToken(
                user_id=user.id,
                token_hash=hash_token(raw),
                expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
            )
        )
        await db.commit()
        link = f"{settings.WEB_ORIGIN}/verify-email?token={raw}"
        await send_verification(user.email, link)

    await audit(db, action="auth.signup", actor=user, ip_address=client_ip(request), user_agent=user_agent(request))
    return await _issue_tokens(db, user, request)


@router.post("/login", response_model=TokenPair)
async def login(payload: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)) -> TokenPair:
    _check_auth_rate_limit(request, "login", limit=10)
    email = payload.email.lower().strip()
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()

    if user is not None and _locked(user):
        await audit(db, action="auth.login_locked", actor=user, status="denied", ip_address=client_ip(request))
        raise HTTPException(status_code=429, detail="Account temporarily locked. Try again shortly.")

    if user is None or not verify_password(payload.password, user.password_hash):
        if user is not None:
            await _register_failed_login(db, user)
        await audit(
            db,
            action="auth.login_failed",
            actor=user,
            status="denied",
            ip_address=client_ip(request),
            detail={"email": email},
        )
        # Identical message for unknown user and bad password.
        raise HTTPException(status_code=401, detail="Invalid email or password")

    if not user.is_active:
        raise HTTPException(status_code=403, detail="This account is disabled")

    if settings.REQUIRE_EMAIL_VERIFICATION and user.google_sub is None and not user.is_verified:
        raise HTTPException(status_code=403, detail="Verify your email before signing in")

    if user.password_hash and password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)

    await _reset_failed_login(db, user)
    tokens = await _issue_tokens(db, user, request)
    await audit(db, action="auth.login", actor=user, ip_address=client_ip(request), user_agent=user_agent(request))
    return tokens


@router.post("/refresh", response_model=TokenPair)
async def refresh_tokens(
    payload: RefreshRequest, request: Request, db: AsyncSession = Depends(get_db)
) -> TokenPair:
    _check_auth_rate_limit(request, "refresh", limit=30)
    token_hash = hash_token(payload.refresh_token)
    session = (await db.execute(select(Session).where(Session.refresh_token_hash == token_hash))).scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    if session.revoked_at is not None or as_utc(session.expires_at) < datetime.now(timezone.utc):
        # Reuse of a rotated/revoked token = likely theft: kill the whole family.
        family = (
            await db.execute(select(Session).where(Session.user_id == session.user_id, Session.revoked_at.is_(None)))
        ).scalars().all()
        for s in family:
            s.revoked_at = datetime.now(timezone.utc)
        await db.commit()
        await audit(db, action="auth.refresh_reuse", status="denied", ip_address=client_ip(request))
        raise HTTPException(status_code=401, detail="Refresh token is no longer valid")

    user = await db.get(User, session.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Account unavailable")

    session.revoked_at = datetime.now(timezone.utc)
    await db.commit()
    return await _issue_tokens(db, user, request, rotated_from=session.id)


@router.post("/logout", status_code=204)
async def logout(ctx: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db)) -> Response:
    ctx.session.revoked_at = datetime.now(timezone.utc)
    await db.commit()
    await audit(db, action="auth.logout", actor=ctx.user)
    return Response(status_code=204)


@router.post("/logout-all", status_code=204)
async def logout_all(
    ctx: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db)
) -> Response:
    rows = (
        await db.execute(select(Session).where(Session.user_id == ctx.user.id, Session.revoked_at.is_(None)))
    ).scalars().all()
    for s in rows:
        s.revoked_at = datetime.now(timezone.utc)
    await db.commit()
    await audit(db, action="auth.logout_all", actor=ctx.user)
    return Response(status_code=204)


@router.get("/sessions")
async def list_sessions(
    ctx: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db)
) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(Session).where(Session.user_id == ctx.user.id, Session.revoked_at.is_(None)).order_by(Session.created_at.desc())
        )
    ).scalars().all()
    return [
        {
            "id": s.id,
            "created_at": s.created_at.isoformat(),
            "expires_at": s.expires_at.isoformat(),
            "ip_address": s.ip_address,
            "user_agent": s.user_agent,
            "current": s.id == ctx.session.id,
        }
        for s in rows
    ]


@router.delete("/sessions/{session_id}", status_code=204)
async def revoke_session(
    session_id: str, ctx: AuthContext = Depends(get_auth_context), db: AsyncSession = Depends(get_db)
) -> Response:
    session = await db.get(Session, session_id)
    if session is None or session.user_id != ctx.user.id:
        raise HTTPException(status_code=404, detail="Session not found")
    session.revoked_at = datetime.now(timezone.utc)
    await db.commit()
    return Response(status_code=204)


# --------------------------------------------------------------------------
# profile
# --------------------------------------------------------------------------
@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user)


@router.patch("/me", response_model=UserOut)
async def update_me(
    payload: dict[str, Any], user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> UserOut:
    if "display_name" in payload:
        name = str(payload["display_name"]).strip()[:120]
        if name:
            user.display_name = name
    if payload.get("theme") in ("dark", "light"):
        user.theme = payload["theme"]
    await db.commit()
    await db.refresh(user)
    return UserOut.model_validate(user)


@router.post("/change-password", status_code=204)
async def change_password(
    payload: ChangePasswordRequest,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> Response:
    if not verify_password(payload.current_password, ctx.user.password_hash):
        await audit(db, action="auth.change_password_failed", actor=ctx.user, status="denied")
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    ctx.user.password_hash = hash_password(payload.new_password)
    rows = (
        await db.execute(select(Session).where(Session.user_id == ctx.user.id, Session.revoked_at.is_(None)))
    ).scalars().all()
    for s in rows:
        s.revoked_at = datetime.now(timezone.utc)
    await db.commit()
    await audit(db, action="auth.change_password", actor=ctx.user)
    return Response(status_code=204)


# --------------------------------------------------------------------------
# password reset
# --------------------------------------------------------------------------
@router.post("/forgot-password", status_code=202)
async def forgot_password(
    payload: ForgotPasswordRequest, request: Request, db: AsyncSession = Depends(get_db)
) -> dict[str, str]:
    _check_auth_rate_limit(request, "forgot", limit=5)
    email = payload.email.lower().strip()
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user is not None and user.is_active:
        raw = new_opaque_token("pr_")
        db.add(
            PasswordResetToken(
                user_id=user.id,
                token_hash=hash_token(raw),
                expires_at=datetime.now(timezone.utc) + timedelta(minutes=settings.PASSWORD_RESET_TTL_MINUTES),
            )
        )
        await db.commit()
        link = f"{settings.WEB_ORIGIN}/reset-password?token={raw}"
        await send_password_reset(user.email, link)
        await audit(db, action="auth.password_reset_requested", actor=user, ip_address=client_ip(request))
    # Always the same answer: never reveal whether an address exists.
    return {"status": "if the address exists, a reset link has been sent"}


@router.post("/reset-password", status_code=204)
async def reset_password(payload: ResetPasswordRequest, db: AsyncSession = Depends(get_db)) -> Response:
    token_hash = hash_token(payload.token)
    row = (await db.execute(select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash))).scalar_one_or_none()
    if row is None or row.used_at is not None:
        raise HTTPException(status_code=400, detail="This reset link is invalid or already used")
    if as_utc(row.expires_at) < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="This reset link has expired")

    user = await db.get(User, row.user_id)
    if user is None:
        raise HTTPException(status_code=400, detail="This reset link is invalid")
    user.password_hash = hash_password(payload.password)
    user.failed_login_count = 0
    user.locked_until = None
    user.is_verified = True
    row.used_at = datetime.now(timezone.utc)
    sessions = (
        await db.execute(select(Session).where(Session.user_id == user.id, Session.revoked_at.is_(None)))
    ).scalars().all()
    for s in sessions:
        s.revoked_at = datetime.now(timezone.utc)
    await db.commit()
    await audit(db, action="auth.password_reset", actor=user)
    return Response(status_code=204)


@router.get("/verify-email")
async def verify_email(token: str, db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    row = (
        await db.execute(select(EmailVerificationToken).where(EmailVerificationToken.token_hash == hash_token(token)))
    ).scalar_one_or_none()
    if row is None or row.used_at is not None:
        raise HTTPException(status_code=400, detail="Invalid or already used verification link")
    if as_utc(row.expires_at) < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Verification link expired")
    user = await db.get(User, row.user_id)
    if user is None:
        raise HTTPException(status_code=400, detail="Invalid verification link")
    user.is_verified = True
    row.used_at = datetime.now(timezone.utc)
    await db.commit()
    await audit(db, action="auth.email_verified", actor=user)
    return {"status": "verified"}


# --------------------------------------------------------------------------
# Google OIDC
# --------------------------------------------------------------------------
@router.get("/google/start")
async def google_start(request: Request) -> RedirectResponse:
    if not (settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET):
        raise HTTPException(status_code=503, detail="Google sign-in is not configured on this instance")
    state = new_opaque_token("gs_")
    # The state is signed into a short-lived cookie so the callback can verify it.
    from app.core.security import _encode  # local import: internal helper

    params = urlencode(
        {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "redirect_uri": settings.GOOGLE_REDIRECT_URI,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "access_type": "online",
            "prompt": "select_account",
        }
    )
    response = RedirectResponse(f"https://accounts.google.com/o/oauth2/v2/auth?{params}")
    signed = _encode({"typ": "oauth_state", "state": state, "exp": int(time.time()) + 600})
    response.set_cookie(
        "armx_oauth_state",
        signed,
        max_age=600,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
    )
    return response


@router.get("/google/callback")
async def google_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    request: Request = None,  # type: ignore[assignment]
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    if error or not code:
        return RedirectResponse(f"{settings.WEB_ORIGIN}/login?error=google_cancelled")

    cookie = request.cookies.get("armx_oauth_state", "") if request else ""
    import jwt as pyjwt

    try:
        decoded = pyjwt.decode(cookie, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except Exception:
        return RedirectResponse(f"{settings.WEB_ORIGIN}/login?error=state_invalid")
    if decoded.get("typ") != "oauth_state" or decoded.get("state") != state:
        return RedirectResponse(f"{settings.WEB_ORIGIN}/login?error=state_mismatch")

    async with httpx.AsyncClient(timeout=20) as client:
        token_resp = await client.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "redirect_uri": settings.GOOGLE_REDIRECT_URI,
                "grant_type": "authorization_code",
            },
        )
        if token_resp.status_code != 200:
            return RedirectResponse(f"{settings.WEB_ORIGIN}/login?error=google_token")
        access = token_resp.json().get("access_token", "")
        info_resp = await client.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {access}"},
        )
    if info_resp.status_code != 200:
        return RedirectResponse(f"{settings.WEB_ORIGIN}/login?error=google_profile")
    info = info_resp.json()
    sub = info.get("sub")
    email = (info.get("email") or "").lower()
    if not sub or not email or not info.get("email_verified", False):
        return RedirectResponse(f"{settings.WEB_ORIGIN}/login?error=google_unverified")

    user = (
        await db.execute(select(User).where((User.google_sub == sub) | (User.email == email)))
    ).scalar_one_or_none()
    if user is None:
        user = User(
            email=email,
            display_name=(info.get("name") or email.split("@")[0])[:120],
            google_sub=sub,
            avatar_url=info.get("picture"),
            role=Role.USER.value,
            is_verified=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
    else:
        user.google_sub = sub
        user.is_verified = True
        if info.get("picture"):
            user.avatar_url = info["picture"]
        await db.commit()

    tokens = await _issue_tokens(db, user, request)  # type: ignore[arg-type]
    await audit(db, action="auth.google_login", actor=user, ip_address=client_ip(request) if request else "")
    # Hand the tokens to the web app via the URL fragment (never logged server-side,
    # never sent to third parties); the client reads and immediately strips it.
    frag = urlencode({"access_token": tokens.access_token, "refresh_token": tokens.refresh_token})
    return RedirectResponse(f"{settings.WEB_ORIGIN}/auth/callback#{frag}")
