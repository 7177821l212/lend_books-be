from pydantic import BaseModel, EmailStr

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
    phone: str | None
    role: UserRole
    investor_id: str | None

    model_config = {"from_attributes": True}
