"""One-shot, race-safe platform-owner bootstrap."""
from __future__ import annotations

from pydantic import EmailStr, TypeAdapter
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import constant_time_compare, hash_password, password_problems
from app.models import Role, SystemFlag, User

SETUP_FLAG = "initial_setup_completed"


async def _admin_count(db: AsyncSession) -> int:
    return int(
        (await db.execute(select(func.count(User.id)).where(User.role == Role.ADMIN.value))).scalar_one()
    )


async def setup_state(db: AsyncSession) -> dict[str, object]:
    complete = await _admin_count(db) > 0
    required = settings.ENV in {"production", "staging"}
    return {
        "required": required,
        "complete": complete,
        "needs_setup": required and not complete,
        "setup_available": bool(settings.INITIAL_SETUP_TOKEN),
        "environment_seed_configured": bool(
            settings.FIRST_ADMIN_EMAIL and settings.FIRST_ADMIN_PASSWORD
        ),
    }


async def seed_initial_admin(db: AsyncSession) -> User | None:
    """Create the environment-defined owner once; never rotate existing users."""
    if not (settings.FIRST_ADMIN_EMAIL and settings.FIRST_ADMIN_PASSWORD):
        return None
    if await _admin_count(db):
        return None

    email = str(TypeAdapter(EmailStr).validate_python(settings.FIRST_ADMIN_EMAIL)).lower()
    problems = password_problems(settings.FIRST_ADMIN_PASSWORD)
    if problems:
        raise RuntimeError("FIRST_ADMIN_PASSWORD " + ", ".join(problems))

    existing = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    if existing is not None:
        existing.role = Role.ADMIN.value
        existing.password_hash = hash_password(settings.FIRST_ADMIN_PASSWORD)
        existing.is_verified = True
        existing.is_active = True
        user = existing
    else:
        user = User(
            email=email,
            display_name=settings.FIRST_ADMIN_DISPLAY_NAME.strip() or "Platform owner",
            password_hash=hash_password(settings.FIRST_ADMIN_PASSWORD),
            role=Role.ADMIN.value,
            is_verified=True,
            is_active=True,
        )
        db.add(user)

    db.add(SystemFlag(key=SETUP_FLAG, value="environment", updated_by="bootstrap"))
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return None
    await db.refresh(user)
    return user


async def complete_setup(
    db: AsyncSession,
    *,
    setup_token: str,
    email: str,
    password: str,
    display_name: str,
) -> User:
    if not settings.INITIAL_SETUP_TOKEN:
        raise ValueError("Protected setup is not enabled")
    if not constant_time_compare(setup_token, settings.INITIAL_SETUP_TOKEN):
        raise PermissionError("Invalid setup token")
    if await _admin_count(db):
        raise RuntimeError("Initial setup is already complete")

    problems = password_problems(password)
    if problems:
        raise ValueError("password " + ", ".join(problems))
    validated_email = str(TypeAdapter(EmailStr).validate_python(email)).lower()
    existing = (
        await db.execute(select(User).where(User.email == validated_email))
    ).scalar_one_or_none()
    if existing is not None:
        existing.role = Role.ADMIN.value
        existing.password_hash = hash_password(password)
        existing.display_name = display_name.strip() or existing.display_name or "Platform owner"
        existing.is_verified = True
        existing.is_active = True
        user = existing
    else:
        user = User(
            email=validated_email,
            display_name=display_name.strip() or "Platform owner",
            password_hash=hash_password(password),
            role=Role.ADMIN.value,
            is_verified=True,
            is_active=True,
        )
        db.add(user)

    db.add(SystemFlag(key=SETUP_FLAG, value="wizard", updated_by="bootstrap"))
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise RuntimeError("Initial setup was completed by another request") from exc
    await db.refresh(user)
    return user
