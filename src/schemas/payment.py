"""Payment Pydantic schemas — collect + missed entries + collector day-view."""

from datetime import date, datetime

from pydantic import BaseModel, Field

from src.constants.enums import PaymentMode


class CollectRequest(BaseModel):
    loan_id: str
    amount: int = Field(gt=0, le=10_00_00_000)
    mode: PaymentMode
    schedule_id: str | None = None
    notes: str | None = Field(default=None, max_length=500)
    proof_photo_url: str | None = Field(default=None, max_length=500)


class MissedRequest(BaseModel):
    loan_id: str
    schedule_id: str
    reason: str = Field(min_length=1, max_length=255)
    notes: str | None = Field(default=None, max_length=500)


class PaymentResponse(BaseModel):
    id: str
    loan_id: str
    schedule_id: str | None = None
    collector_id: str
    is_missed: bool
    missed_reason: str | None = None
    amount: int
    mode: PaymentMode | None = None
    notes: str | None = None
    proof_photo_url: str | None = None
    collected_at: datetime

    model_config = {"from_attributes": True}


class PickupItem(BaseModel):
    loan_id: str
    customer_id: str
    customer_name: str
    customer_phone: str
    customer_location: str | None = None
    schedule_id: str
    sequence: int
    due_date: date
    due_amount: int
    is_overdue: bool

    model_config = {"from_attributes": True}


class MyDayResponse(BaseModel):
    today: date
    pickups: list[PickupItem]
    target_total: int
    collected_today: int
    pickup_count: int
    overdue_count: int
