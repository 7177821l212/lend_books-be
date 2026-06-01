from datetime import datetime

from pydantic import BaseModel

from src.constants.enums import PaymentMode


class CollectRequest(BaseModel):
    loan_id: str
    amount: int
    mode: PaymentMode
    notes: str | None = None
    proof_photo_url: str | None = None


class MissedRequest(BaseModel):
    loan_id: str
    installment_id: str
    notes: str | None = None


class PaymentResponse(BaseModel):
    id: str
    loan_id: str
    collector_id: str
    amount: int
    mode: PaymentMode
    notes: str | None
    proof_photo_url: str | None
    collected_at: datetime

    model_config = {"from_attributes": True}
