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
    RescheduleMode,
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
    is_active: bool = True
    schedule_version: int = 1
    replaced_at: datetime | None = None

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


class RescheduleInstallment(BaseModel):
    due_date: date
    due_amount: int = Field(gt=0, le=10_00_00_000)


class RescheduleRequest(BaseModel):
    """Investor-approved replacement plan for currently open schedule rows.

    Paid rows and the payment ledger are never touched — only rows that still
    expect money are replaced, and the old rows survive as inactive history.
    """

    reason: str = Field(min_length=3, max_length=255)
    mode: RescheduleMode = RescheduleMode.MANUAL
    # MANUAL only
    installments: list[RescheduleInstallment] = Field(
        default_factory=list, max_length=10_000
    )
    # SAME_INSTALLMENT only
    installment_amount: int | None = Field(default=None, gt=0, le=10_00_00_000)
    # Optional override for the first new due date (defaults to the earliest open row)
    start_date: date | None = None

    @model_validator(mode="after")
    def validate_mode_inputs(self) -> "RescheduleRequest":
        if self.mode is RescheduleMode.MANUAL:
            if not self.installments:
                raise ValueError("manual mode requires at least one installment")
            dates = [row.due_date for row in self.installments]
            if dates != sorted(dates):
                raise ValueError(
                    "rescheduled installment dates must be in ascending order"
                )
        elif self.installments:
            raise ValueError(
                f"{self.mode.value} mode derives its own rows; omit 'installments'"
            )
        needs_amount = self.mode is RescheduleMode.SAME_INSTALLMENT
        if needs_amount and self.installment_amount is None:
            raise ValueError("same_installment mode requires 'installment_amount'")
        if not needs_amount and self.installment_amount is not None:
            raise ValueError(
                "'installment_amount' only applies to same_installment mode"
            )
        return self


class SchedulePreviewRow(BaseModel):
    sequence: int
    due_date: date
    due_amount: int
    paid_amount: int = 0


class ReschedulePreview(BaseModel):
    """Old remaining schedule vs. proposed replacement — nothing is written."""

    remaining_balance: int
    current: list[SchedulePreviewRow]
    proposed: list[SchedulePreviewRow]
    current_total: int
    proposed_total: int
    current_end_date: date | None = None
    proposed_end_date: date | None = None


class ScheduleRevisionResponse(BaseModel):
    id: str
    loan_id: str
    version: int
    reason: str
    effective_from: date
    created_by: str
    created_by_name: str = ""
    created_at: datetime

    model_config = {"from_attributes": True}
