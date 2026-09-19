"""Payment Pydantic schemas — collect + missed entries + collector day-view."""

from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator

from src.constants.enums import CollectionMode, PaymentMode
from src.utils.time import business_today


class CollectRequest(BaseModel):
    loan_id: str
    amount: int = Field(gt=0, le=10_00_00_000)
    mode: PaymentMode
    # The day the money actually changed hands. A collector writes up a round
    # afterwards, so a receipt may be entered a day or two late and must still
    # land on its real date. Defaults to now when omitted. Future dates are
    # rejected — cash cannot be received tomorrow.
    collected_on: date | None = None
    schedule_id: str | None = None
    notes: str | None = Field(default=None, max_length=500)
    proof_photo_url: str | None = Field(default=None, max_length=500)

    @field_validator("collected_on")
    @classmethod
    def collection_cannot_be_in_the_future(cls, value: date | None) -> date | None:
        if value is not None and value > business_today():
            raise ValueError("collection date cannot be in the future")
        return value

    @field_validator("proof_photo_url")
    @classmethod
    def proof_must_reference_an_uploaded_photo(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.startswith("photos/") or any(
            part in {"", ".", ".."} for part in value.split("/")
        ):
            raise ValueError("proof_photo_url must reference an uploaded photo")
        return value


class MissedRequest(BaseModel):
    """A visit where nothing was collected.

    SCHEDULE loans attach it to the installment that was missed. BALANCE loans
    have no installments, so it is recorded against the loan and the day —
    `schedule_id` is omitted and `missed_on` says which day it was.
    """

    loan_id: str
    schedule_id: str | None = None
    missed_on: date | None = None
    reason: str = Field(min_length=1, max_length=255)
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("missed_on")
    @classmethod
    def missed_visit_cannot_be_in_the_future(cls, value: date | None) -> date | None:
        if value is not None and value > business_today():
            raise ValueError("a missed visit cannot be in the future")
        return value


class PaymentAllocationResponse(BaseModel):
    installment_id: str
    sequence: int
    due_date: date
    amount: int


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
    allocations: list[PaymentAllocationResponse] = []

    model_config = {"from_attributes": True}


class PickupItem(BaseModel):
    """One line on the collector's daily round.

    A SCHEDULE loan contributes an installment that is due today or overdue, so
    it carries `schedule_id`, `sequence` and `due_date`. A BALANCE loan has no
    schedule: it appears every day while it is active, those three fields are
    null, and `due_amount` is simply what is left to collect.
    """

    loan_id: str
    customer_id: str
    customer_name: str
    customer_phone: str
    customer_location: str | None = None
    collection_mode: CollectionMode = CollectionMode.SCHEDULE
    # Which of this customer's loans this is, and when it was given — without
    # these, two live loans for one customer are indistinguishable on the round.
    loan_number: int = 1
    start_date: date | None = None
    missed_count: int = 0
    schedule_id: str | None = None
    sequence: int | None = None
    due_date: date | None = None
    due_amount: int
    is_overdue: bool = False

    model_config = {"from_attributes": True}


class MyDayResponse(BaseModel):
    today: date
    pickups: list[PickupItem]
    # Only SCHEDULE loans contribute: a balance loan has no amount expected
    # today, so counting its whole remaining balance would make the day's
    # target meaningless.
    target_total: int
    collected_today: int
    pickup_count: int
    overdue_count: int
