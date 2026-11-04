"""Authentication: password, rotating sessions, HttpOnly cookies, Resend email.

Legacy bearer tokens remain supported for existing API clients and tests. The
browser now uses HttpOnly SameSite cookies as the primary source of truth; the
refresh token never enters localStorage. Password reset and verification links
are single-use, hashed at rest and delivered through the Resend REST API.
"""
from __future__ import annotations

import logging
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import audit
from app.core.bootstrap import setup_state
from app.core.config import settings
from app.core.db import as_utc, get_db
from app.core.deps import AuthContext, client_ip, get_auth_context, get_current_user, user_agent
from app.core.mailer import (
    password_reset_email,
    queue_email,
    recent_delivery,
    verification_email,
)
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
    RegisterRequest,
    ResendVerificationRequest,
    ResetPasswordRequest,
    SignupRequest,
    TokenPair,
    UserOut,
    VerifyEmailRequest,
)

router = APIRouter(prefix="/auth", tags=["auth"])
log = logging.getLogger(__name__)

GENERIC_RESET_MESSAGE = (
    "If an account exists for this email, you will receive password recovery instructions shortly."
)
GENERIC_VERIFICATION_MESSAGE = (
    "If an account exists and needs verification, you will receive instructions shortly."
)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _request_id(request: Request) -> str:
    return str(getattr(request.state, "request_id", "") or "")


async def _issue_tokens(
    db: AsyncSession,
    user: User,
    request: Request,
    *,
    rotated_from: str | None = None,
    remember_me: bool = True,
) -> tuple[TokenPair, int]:
    ttl_seconds = (
        settings.REFRESH_TOKEN_TTL_DAYS * 86400
        if remember_me
        else settings.SESSION_REFRESH_TTL_HOURS * 3600
    )
    refresh = new_opaque_token("rt_")
    session = Session(
        user_id=user.id,
        refresh_token_hash=hash_token(refresh),
        expires_at=_now() + timedelta(seconds=ttl_seconds),
        rotated_from=rotated_from,
        user_agent=user_agent(request),
        ip_address=client_ip(request),
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    tokens = TokenPair(
        access_token=create_access_token(user_id=user.id, role=user.role, session_id=session.id),
        refresh_token=refresh,
        expires_in=settings.ACCESS_TOKEN_TTL_MINUTES * 60,
    )
    return tokens, ttl_seconds


def _set_auth_cookies(response: Response, tokens: TokenPair, refresh_ttl_seconds: int) -> None:
    common = {
        "httponly": True,
        "secure": settings.is_production,
        "samesite": "lax",
    }
    response.set_cookie(
        settings.ACCESS_COOKIE_NAME,
        tokens.access_token,
        max_age=settings.ACCESS_TOKEN_TTL_MINUTES * 60,
        path=settings.API_PREFIX,
        **common,
    )
    response.set_cookie(
        settings.REFRESH_COOKIE_NAME,
        tokens.refresh_token,
        max_age=refresh_ttl_seconds,
        path=f"{settings.API_PREFIX}/auth",
        **common,
    )


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(settings.ACCESS_COOKIE_NAME, path=settings.API_PREFIX)
    response.delete_cookie(settings.REFRESH_COOKIE_NAME, path=f"{settings.API_PREFIX}/auth")


def _check_auth_rate_limit(request: Request, bucket: str, limit: int = 10) -> None:
    key = f"auth:{bucket}:{client_ip(request)}"
    ok, _ = rate_limiter.hit(key, limit)
    if not ok:
        raise HTTPException(status_code=429, detail="Too many attempts. Try again in a minute.")


def _locked(user: User) -> bool:
    if user.locked_until is None:
        return False
    return as_utc(user.locked_until) > _now()


async def _register_failed_login(db: AsyncSession, user: User) -> None:
    user.failed_login_count += 1
    if user.failed_login_count >= settings.LOGIN_MAX_ATTEMPTS:
        user.locked_until = _now() + timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES)
        user.failed_login_count = 0
    await db.commit()


async def _reset_failed_login(db: AsyncSession, user: User) -> None:
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = _now()
    await db.commit()


async def _send_verification(
    db: AsyncSession,
    background: BackgroundTasks | None,
    user: User,
    request_id: str,
) -> None:
    raw = new_opaque_token("ev_")
    row = EmailVerificationToken(
        user_id=user.id,
        token_hash=hash_token(raw),
        expires_at=_now() + timedelta(hours=settings.EMAIL_VERIFICATION_TTL_HOURS),
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    link = f"{settings.auth_base_url}/verify-email?token={raw}"
    subject, html_body, text_body = verification_email(link, settings.EMAIL_VERIFICATION_TTL_HOURS)
    await queue_email(
        db,
        to=user.email,
        purpose="email_verification",
        subject=subject,
        html_body=html_body,
        text_body=text_body,
        user_id=user.id,
        token_id=row.id,
        request_id=request_id,
        link=link,
        background=background,
    )


# --------------------------------------------------------------------------
# signup / register / login
# --------------------------------------------------------------------------
async def _signup_impl(
    payload: SignupRequest,
    request: Request,
    response: Response,
    background: BackgroundTasks,
    db: AsyncSession,
) -> TokenPair:
    _check_auth_rate_limit(request, "signup", limit=5)
    if (await setup_state(db))["needs_setup"]:
        raise HTTPException(status_code=503, detail="Complete protected platform setup before creating users")
    email = str(payload.email).lower().strip()
    existing = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if existing is not None:
        # Generic conflict; never expose account details or role.
        raise HTTPException(status_code=409, detail="Could not create the account with those details")

    # Public signup can only create role=user. The first admin comes from the CLI.
    user = User(
        email=email,
        display_name=payload.display_name.strip() or email.split("@")[0][:60],
        password_hash=hash_password(payload.password),
        role=Role.USER.value,
        is_verified=False,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    request_id = _request_id(request)
    try:
        await _send_verification(db, background, user, request_id)
    except Exception as exc:  # pragma: no cover - external fault boundary
        log.exception("Could not queue verification email for new account %s", user.id)
        await audit(
            db,
            action="auth.verification_email_failed",
            actor=user,
            status="error",
            detail={"request_id": request_id, "error": str(exc)[:300]},
        )
    await audit(db, action="auth.signup", actor=user, ip_address=client_ip(request), user_agent=user_agent(request))
    tokens, ttl = await _issue_tokens(db, user, request, remember_me=payload.remember_me)
    _set_auth_cookies(response, tokens, ttl)
    return tokens


@router.post("/signup", response_model=TokenPair, status_code=201)
async def signup(
    payload: SignupRequest,
    request: Request,
    response: Response,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> TokenPair:
    return await _signup_impl(payload, request, response, background, db)


@router.post("/register", response_model=TokenPair, status_code=201)
async def register(
    payload: RegisterRequest,
    request: Request,
    response: Response,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> TokenPair:
    return await _signup_impl(payload, request, response, background, db)


@router.post("/login", response_model=TokenPair)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenPair:
    _check_auth_rate_limit(request, "login", limit=10)
    email = str(payload.email).lower().strip()
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
    tokens, ttl = await _issue_tokens(db, user, request, remember_me=payload.remember_me)
    _set_auth_cookies(response, tokens, ttl)
    await audit(db, action="auth.login", actor=user, ip_address=client_ip(request), user_agent=user_agent(request))
    return tokens


# --------------------------------------------------------------------------
# refresh / logout / sessions
# --------------------------------------------------------------------------
@router.post("/refresh", response_model=TokenPair)
async def refresh_tokens(
    request: Request,
    response: Response,
    payload: RefreshRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> TokenPair:
    _check_auth_rate_limit(request, "refresh", limit=30)
    raw_refresh = (payload.refresh_token if payload and payload.refresh_token else "") or request.cookies.get(
        settings.REFRESH_COOKIE_NAME, ""
    )
    if not raw_refresh:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    token_hash = hash_token(raw_refresh)
    session = (await db.execute(select(Session).where(Session.refresh_token_hash == token_hash))).scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    if session.revoked_at is not None or as_utc(session.expires_at) < _now():
        # Reuse of a rotated/revoked token = likely theft: kill the whole family.
        family = (
            await db.execute(select(Session).where(Session.user_id == session.user_id, Session.revoked_at.is_(None)))
        ).scalars().all()
        for s in family:
            s.revoked_at = _now()
        await db.commit()
        await audit(db, action="auth.refresh_reuse", status="denied", ip_address=client_ip(request))
        raise HTTPException(status_code=401, detail="Refresh token is no longer valid")

    user = await db.get(User, session.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Account unavailable")

    remember_me = (as_utc(session.expires_at) - _now()).total_seconds() > 86400
    session.revoked_at = _now()
    await db.commit()
    tokens, ttl = await _issue_tokens(db, user, request, rotated_from=session.id, remember_me=remember_me)
    _set_auth_cookies(response, tokens, ttl)
    return tokens


@router.post("/logout", status_code=204)
async def logout(
    response: Response,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> Response:
    ctx.session.revoked_at = _now()
    await db.commit()
    await audit(db, action="auth.logout", actor=ctx.user)
    _clear_auth_cookies(response)
    response.status_code = 204
    return response


@router.post("/logout-all", status_code=204)
async def logout_all(
    response: Response,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> Response:
    rows = (
        await db.execute(select(Session).where(Session.user_id == ctx.user.id, Session.revoked_at.is_(None)))
    ).scalars().all()
    for s in rows:
        s.revoked_at = _now()
    await db.commit()
    await audit(db, action="auth.logout_all", actor=ctx.user)
    _clear_auth_cookies(response)
    response.status_code = 204
    return response


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
    session_id: str,
    response: Response,
    ctx: AuthContext = Depends(get_auth_context),
    db: AsyncSession = Depends(get_db),
) -> Response:
    session = await db.get(Session, session_id)
    if session is None or session.user_id != ctx.user.id:
        raise HTTPException(status_code=404, detail="Session not found")
    session.revoked_at = _now()
    if session.id == ctx.session.id:
        _clear_auth_cookies(response)
    await db.commit()
    response.status_code = 204
    return response


# --------------------------------------------------------------------------
# profile / password change
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
    response: Response,
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
        s.revoked_at = _now()
    await db.commit()
    await audit(db, action="auth.change_password", actor=ctx.user)
    _clear_auth_cookies(response)
    response.status_code = 204
    return response


# --------------------------------------------------------------------------
# password reset — Resend REST, single-use hashed token, 15-minute expiry
# --------------------------------------------------------------------------
@router.post("/forgot-password", status_code=202)
async def forgot_password(
    payload: ForgotPasswordRequest,
    request: Request,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    _check_auth_rate_limit(request, "forgot", limit=5)
    email = str(payload.email).lower().strip()
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    request_id = _request_id(request)

    if user is not None and user.is_active:
        # Cooldown is checked before minting a token: duplicate requests do not
        # create extra usable recovery links.
        recent = await recent_delivery(db, email, "password_reset")
        if recent is None:
            raw = new_opaque_token("pr_")
            row = PasswordResetToken(
                user_id=user.id,
                token_hash=hash_token(raw),
                expires_at=_now() + timedelta(minutes=settings.PASSWORD_RESET_TTL_MINUTES),
            )
            db.add(row)
            await db.commit()
            await db.refresh(row)
            link = f"{settings.auth_base_url}/reset-password?token={raw}"
            subject, html_body, text_body = password_reset_email(link, settings.PASSWORD_RESET_TTL_MINUTES)
            try:
                await queue_email(
                    db,
                    to=user.email,
                    purpose="password_reset",
                    subject=subject,
                    html_body=html_body,
                    text_body=text_body,
                    user_id=user.id,
                    token_id=row.id,
                    request_id=request_id,
                    link=link,
                    background=background,
                )
            except Exception as exc:  # pragma: no cover - external fault boundary
                log.exception("Could not queue password-reset email for %s", user.id)
                await audit(
                    db,
                    action="auth.password_reset_email_failed",
                    actor=user,
                    status="error",
                    detail={"request_id": request_id, "error": str(exc)[:300]},
                )
            await audit(db, action="auth.password_reset_requested", actor=user, ip_address=client_ip(request))
    # Always the same answer: never reveal whether an address exists.
    return {"status": "accepted", "message": GENERIC_RESET_MESSAGE}


@router.post("/reset-password", status_code=204)
async def reset_password(
    payload: ResetPasswordRequest,
    response: Response,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    token_hash = hash_token(payload.token)
    row = (await db.execute(select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash))).scalar_one_or_none()
    if row is None or row.used_at is not None:
        raise HTTPException(status_code=400, detail="This reset link is invalid or already used")
    if as_utc(row.expires_at) < _now():
        raise HTTPException(status_code=400, detail="This reset link has expired")

    user = await db.get(User, row.user_id)
    if user is None:
        raise HTTPException(status_code=400, detail="This reset link is invalid")
    user.password_hash = hash_password(payload.password)
    user.failed_login_count = 0
    user.locked_until = None
    user.is_verified = True
    row.used_at = _now()
    sessions = (
        await db.execute(select(Session).where(Session.user_id == user.id, Session.revoked_at.is_(None)))
    ).scalars().all()
    for s in sessions:
        s.revoked_at = _now()
    await db.commit()
    await audit(
        db,
        action="auth.password_reset",
        actor=user,
        ip_address=client_ip(request),
        detail={"request_id": _request_id(request)},
    )
    # No automatic login: every old session is revoked and cookies are cleared.
    _clear_auth_cookies(response)
    response.status_code = 204
    return response


# --------------------------------------------------------------------------
# email verification
# --------------------------------------------------------------------------
async def _verify_email_token(db: AsyncSession, token: str) -> dict[str, str]:
    row = (
        await db.execute(select(EmailVerificationToken).where(EmailVerificationToken.token_hash == hash_token(token)))
    ).scalar_one_or_none()
    if row is None or row.used_at is not None:
        raise HTTPException(status_code=400, detail="Invalid or already used verification link")
    if as_utc(row.expires_at) < _now():
        raise HTTPException(status_code=400, detail="Verification link expired")
    user = await db.get(User, row.user_id)
    if user is None:
        raise HTTPException(status_code=400, detail="Invalid verification link")
    now = _now()
    user.is_verified = True
    rows = (
        await db.execute(
            select(EmailVerificationToken).where(
                EmailVerificationToken.user_id == user.id,
                EmailVerificationToken.used_at.is_(None),
            )
        )
    ).scalars().all()
    for item in rows:
        item.used_at = now
    await db.commit()
    await audit(db, action="auth.email_verified", actor=user)
    return {"status": "verified", "message": "Email verified. You can sign in now."}


@router.get("/verify-email")
async def verify_email_link(token: str, db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    """Compatibility for links already in mailboxes; the UI posts the token."""
    return await _verify_email_token(db, token)


@router.post("/verify-email")
async def verify_email(payload: VerifyEmailRequest, db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    return await _verify_email_token(db, payload.token)


@router.post("/resend-verification", status_code=202)
async def resend_verification(
    payload: ResendVerificationRequest,
    request: Request,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    _check_auth_rate_limit(request, "resend-verification", limit=5)
    email = str(payload.email).lower().strip()
    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if user is not None and not user.is_verified and user.is_active:
        recent = await recent_delivery(db, email, "email_verification")
        if recent is None:
            try:
                await _send_verification(db, background, user, _request_id(request))
                await audit(db, action="auth.verification_resent", actor=user, ip_address=client_ip(request))
            except Exception as exc:  # pragma: no cover - external fault boundary
                log.exception("Could not resend verification email")
                await audit(
                    db,
                    action="auth.verification_resend_failed",
                    actor=user,
                    status="error",
                    detail={"error": str(exc)[:300], "request_id": _request_id(request)},
                )
    return {"status": "accepted", "message": GENERIC_VERIFICATION_MESSAGE}


@router.get("/verification-status")
async def verification_status(ctx: AuthContext = Depends(get_auth_context)) -> dict[str, Any]:
    return {
        "email": ctx.user.email,
        "is_verified": ctx.user.is_verified,
        "required": settings.REQUIRE_EMAIL_VERIFICATION,
    }


@router.get("/csrf")
async def csrf_token(request: Request, response: Response) -> dict[str, str]:
    """Issue the readable double-submit cookie and return its value once."""
    token = request.cookies.get(settings.CSRF_COOKIE_NAME) or secrets.token_urlsafe(32)
    response.set_cookie(
        settings.CSRF_COOKIE_NAME,
        token,
        max_age=settings.REFRESH_TOKEN_TTL_DAYS * 86400,
        httponly=False,
        secure=settings.is_production,
        samesite="lax",
        path="/",
    )
    return {"csrf_token": token, "cookie_name": settings.CSRF_COOKIE_NAME}


# --------------------------------------------------------------------------
# Google OIDC (cookies, no token fragment)
# --------------------------------------------------------------------------
@router.get("/google/start")
async def google_start(request: Request) -> RedirectResponse:
    if not (settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET):
        raise HTTPException(status_code=503, detail="Google sign-in is not configured on this instance")
    state = new_opaque_token("gs_")
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
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    base = settings.auth_base_url
    if error or not code:
        return RedirectResponse(f"{base}/login?error=google_cancelled")

    cookie = request.cookies.get("armx_oauth_state", "")
    import jwt as pyjwt

    try:
        decoded = pyjwt.decode(cookie, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except Exception:
        return RedirectResponse(f"{base}/login?error=state_invalid")
    if decoded.get("typ") != "oauth_state" or decoded.get("state") != state:
        return RedirectResponse(f"{base}/login?error=state_mismatch")

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
            return RedirectResponse(f"{base}/login?error=google_token")
        access = token_resp.json().get("access_token", "")
        info_resp = await client.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {access}"},
        )
    if info_resp.status_code != 200:
        return RedirectResponse(f"{base}/login?error=google_profile")
    info = info_resp.json()
    sub = info.get("sub")
    email = (info.get("email") or "").lower()
    if not sub or not email or not info.get("email_verified", False):
        return RedirectResponse(f"{base}/login?error=google_unverified")

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

    tokens, ttl = await _issue_tokens(db, user, request, remember_me=True)
    await audit(db, action="auth.google_login", actor=user, ip_address=client_ip(request))
    response = RedirectResponse(f"{base}/auth/callback?google=1")
    _set_auth_cookies(response, tokens, ttl)
    response.delete_cookie("armx_oauth_state")
    return response
