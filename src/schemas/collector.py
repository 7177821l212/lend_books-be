"""Collector-related schemas."""

from pydantic import BaseModel, EmailStr, Field


class CollectorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=20)
    password: str = Field(min_length=6, max_length=128)


class CollectorResponse(BaseModel):
    id: str
    name: str
    email: str
    phone: str | None = None
    is_active: bool

    model_config = {"from_attributes": True}
