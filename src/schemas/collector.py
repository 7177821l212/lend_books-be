"""Collector-related schemas."""

from pydantic import BaseModel, EmailStr, Field


class CollectorCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=20)
    password: str = Field(min_length=6, max_length=128)


class CollectorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    phone: str | None = Field(default=None, max_length=20)
    photo_url: str | None = Field(default=None, max_length=1024)


class CollectorResponse(BaseModel):
    id: str
    name: str
    email: str
    phone: str | None = None
    photo_url: str | None = None
    is_active: bool

    model_config = {"from_attributes": True}
