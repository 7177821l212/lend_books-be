"""Loan Pydantic schemas — supports Model A + Model B, PCT + FIXED interest."""

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

from src.constants.enums import (
    InstallmentStatus,
    InterestType,
    LendingModel,
    LoanStatus,
    RepaymentFrequency,
)


class LoanCreate(BaseModel):
    customer_id: str
    collector_id: str
    principal: int = Field(gt=0, le=10_00_00_000)  # ≤ 10 Cr
    interest_type: InterestType = InterestType.PCT
    interest_value: float = Field(ge=0)
    lending_model: LendingModel = LendingModel.MODEL_A
    repayment_frequency: RepaymentFrequency = RepaymentFrequency.DAILY
    frequency_meta: dict[str, Any] | None = None
    total_installments: int = Field(gt=0, le=10_000)
    start_date: date

    @model_validator(mode="after")
    def validate_pct_range(self) -> "LoanCreate":
        if self.interest_type is InterestType.PCT and not 0 <= self.interest_value <= 100:
            raise ValueError("percentage interest must be between 0 and 100")
        return self


class InstallmentResponse(BaseModel):
    id: str
    sequence: int
    due_date: date
    due_amount: int
    paid_amount: int = 0
    status: InstallmentStatus

    model_config = {"from_attributes": True}


class LoanSummary(BaseModel):
    id: str
    customer_id: str
    customer_name: str
    collector_id: str
    collector_name: str

    principal: int
    interest_type: InterestType
    interest_value: float
    lending_model: LendingModel

    disbursed: int
    repayable: int
    profit: int

    repayment_frequency: RepaymentFrequency
    total_installments: int
    installment_amount: int  # base (floor) per-installment amount
    installment_amount_max: int = 0  # largest single installment when remainder distributes
    start_date: date

    status: LoanStatus
    outstanding: int
    repaid: int
    repaid_pct: float
    paid_count: int = 0
    overdue_count: int = 0
    closed_at: datetime | None = None

    model_config = {"from_attributes": True}


class LoanDetail(LoanSummary):
    installments: list[InstallmentResponse] = []


class CloseLoanRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=255)


class AssignCollectorRequest(BaseModel):
    collector_id: str
