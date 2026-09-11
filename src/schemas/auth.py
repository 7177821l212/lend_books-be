"""Auth-related Pydantic schemas."""

from pydantic import BaseModel, EmailStr, Field

from src.constants.enums import UserRole


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class UserMe(BaseModel):
    id: str
    email: str
    name: str
    phone: str | None = None
    role: UserRole
    is_active: bool = True
    photo_url: str | None = None

    model_config = {"from_attributes": True}


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=6, max_length=128)
