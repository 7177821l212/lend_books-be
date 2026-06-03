"""Collector-related schemas."""

from pydantic import BaseModel


class CollectorResponse(BaseModel):
    id: str
    name: str
    email: str
    phone: str | None = None
    is_active: bool

    model_config = {"from_attributes": True}
