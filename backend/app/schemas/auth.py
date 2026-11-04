from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.core.security import password_problems


class SignupRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)
    display_name: str = Field(default="", max_length=120)
    full_name: str | None = Field(default=None, max_length=120)
    confirm_password: str | None = Field(default=None, max_length=200)
    # Legacy /signup callers omitted both fields; new /register UI sends them.
    terms_accepted: bool = True
    remember_me: bool = False

    @field_validator("password")
    @classmethod
    def _strength(cls, v: str) -> str:
        problems = password_problems(v)
        if problems:
            raise ValueError("password " + ", ".join(problems))
        return v

    @model_validator(mode="after")
    def _check(self) -> "SignupRequest":
        if not self.terms_accepted:
            raise ValueError("You must accept the terms to create an account")
        if self.confirm_password is not None and self.confirm_password != self.password:
            raise ValueError("Passwords do not match")
        if not self.display_name.strip() and self.full_name:
            self.display_name = self.full_name.strip()[:120]
        return self


class RegisterRequest(SignupRequest):
    """Modern /register contract: explicit terms acceptance is mandatory."""

    terms_accepted: bool = Field(description="Must be true")


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)
    remember_me: bool = False


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    # When omitted, the HttpOnly armx_refresh cookie is used.
    refresh_token: str | None = Field(default=None, min_length=10, max_length=400)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=10, max_length=400)
    password: str = Field(min_length=10, max_length=200)
    confirm_password: str | None = Field(default=None, max_length=200)

    @field_validator("password")
    @classmethod
    def _strength(cls, v: str) -> str:
        problems = password_problems(v)
        if problems:
            raise ValueError("password " + ", ".join(problems))
        return v

    @model_validator(mode="after")
    def _check(self) -> "ResetPasswordRequest":
        if self.confirm_password is not None and self.confirm_password != self.password:
            raise ValueError("Passwords do not match")
        return self


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


class VerifyEmailRequest(BaseModel):
    token: str = Field(min_length=10, max_length=400)


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class UserOut(BaseModel):
    id: str
    email: str
    display_name: str
    role: str
    is_verified: bool
    is_active: bool
    theme: str
    avatar_url: str | None = None
    last_login_at: datetime | None = None

    model_config = {"from_attributes": True}


class SessionOut(BaseModel):
    id: str
    created_at: str
    ip_address: str
    user_agent: str
    current: bool = False
