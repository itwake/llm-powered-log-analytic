from __future__ import annotations

from pydantic import BaseModel


class UserOut(BaseModel):
    id: str
    email: str
    username: str
    full_name: str | None = None


class AuthUserResponse(BaseModel):
    user: UserOut
