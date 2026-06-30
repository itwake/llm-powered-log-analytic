from __future__ import annotations

from pydantic import BaseModel, Field


class UserOut(BaseModel):
    id: str
    organization_id: str
    email: str
    username: str
    role: str
    is_active: bool = True


class RegisterRequest(BaseModel):
    email: str
    username: str = Field(min_length=2)
    full_name: str | None = None
    password: str = Field(min_length=8)


class LoginRequest(BaseModel):
    email_or_username: str
    password: str


class AuthUserResponse(BaseModel):
    user: UserOut
