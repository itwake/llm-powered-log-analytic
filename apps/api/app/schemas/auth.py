from __future__ import annotations

from pydantic import BaseModel, Field


class UserOut(BaseModel):
    id: str
    email: str
    username: str
    role: str
    is_active: bool = True
    has_copilot_credential: bool = False


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


class CopilotStartRequest(BaseModel):
    github_base_url: str = Field(
        default="https://github.com",
        description=(
            "Accepted for backwards compatibility; Copilot OAuth always uses "
            "https://github.com regardless of this value."
        ),
    )


class CopilotCheckRequest(BaseModel):
    auth_id: str
