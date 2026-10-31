from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.core.security import password_problems


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)
    display_name: str = Field(default="", max_length=120)

    @field_validator("password")
    @classmethod
    def _strength(cls, v: str) -> str:
        problems = password_problems(v)
        if problems:
            raise ValueError("password " + ", ".join(problems))
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=10, max_length=400)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=10, max_length=400)
    password: str = Field(min_length=10, max_length=200)

    @field_validator("password")
    @classmethod
    def _strength(cls, v: str) -> str:
        problems = password_problems(v)
        if problems:
            raise ValueError("password " + ", ".join(problems))
        return v


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=10, max_length=200)

    @field_validator("new_password")
    @classmethod
    def _strength(cls, v: str) -> str:
        problems = password_problems(v)
        if problems:
            raise ValueError("password " + ", ".join(problems))
        return v


class UserOut(BaseModel):
    id: str
    email: str
    display_name: str
    role: str
    is_verified: bool
    theme: str
    avatar_url: str | None = None

    model_config = {"from_attributes": True}


class SessionOut(BaseModel):
    id: str
    created_at: str
    ip_address: str
    user_agent: str
    current: bool = False
