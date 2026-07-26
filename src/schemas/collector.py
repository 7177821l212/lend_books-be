"""Collector-related schemas."""

from datetime import datetime

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


class LocationReport(BaseModel):
    """Sent by the collector app while it's open — a live location ping."""

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    accuracy: float | None = Field(default=None, ge=0)
    # Client-side capture time (device clock) — falls back to server time if omitted.
    recorded_at: datetime | None = None


class CollectorLocationResponse(BaseModel):
    collector_id: str
    collector_name: str
    photo_url: str | None = None
    latitude: float
    longitude: float
    accuracy: float | None = None
    recorded_at: datetime

    model_config = {"from_attributes": True}
