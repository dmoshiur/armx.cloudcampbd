"""Protected one-time platform setup endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import audit
from app.core.bootstrap import complete_setup, setup_state
from app.core.db import get_db
from app.core.deps import client_ip
from app.core.security import password_problems, rate_limiter

router = APIRouter(prefix="/setup", tags=["setup"])


class InitialSetupRequest(BaseModel):
    setup_token: str = Field(min_length=32, max_length=500)
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)
    display_name: str = Field(default="Platform owner", max_length=120)

    @field_validator("password")
    @classmethod
    def _strong_password(cls, value: str) -> str:
        problems = password_problems(value)
        if problems:
            raise ValueError("password " + ", ".join(problems))
        return value


@router.get("/status")
async def status_endpoint(db: AsyncSession = Depends(get_db)) -> dict[str, object]:
    return await setup_state(db)


@router.post("/complete", status_code=status.HTTP_201_CREATED)
async def complete_endpoint(
    payload: InitialSetupRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    allowed, _remaining = rate_limiter.hit(f"setup:{client_ip(request)}", 5, 300)
    if not allowed:
        raise HTTPException(status_code=429, detail="Too many setup attempts; try again later")
    try:
        user = await complete_setup(
            db,
            setup_token=payload.setup_token,
            email=str(payload.email),
            password=payload.password,
            display_name=payload.display_name,
        )
    except PermissionError as exc:
        await audit(
            db,
            action="setup.denied",
            status="denied",
            ip_address=client_ip(request),
        )
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await audit(
        db,
        action="setup.completed",
        actor=user,
        target=user.id,
        ip_address=client_ip(request),
        detail={"method": "protected_wizard"},
    )
    return {"complete": True, "email": user.email, "next": "/login"}
