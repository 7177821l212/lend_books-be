from datetime import date

from pydantic import BaseModel, model_validator

from src.constants.enums import (
    InstallmentStatus,
    LendingModel,
    LoanStatus,
    RepaymentFrequency,
)


class LoanCreate(BaseModel):
    customer_id: str
    collector_id: str
    principal: int
    interest_rate: float
    lending_model: LendingModel = LendingModel.MODEL_A
    repayment_frequency: RepaymentFrequency = RepaymentFrequency.DAILY
    total_installments: int
    start_date: date

    @model_validator(mode="after")
    def validate_amounts(self) -> "LoanCreate":
        if self.principal <= 0:
            raise ValueError("principal must be positive")
        if not (1 <= self.interest_rate <= 100):
            raise ValueError("interest_rate must be between 1 and 100")
        return self


class InstallmentResponse(BaseModel):
    id: str
    sequence: int
    due_date: date
    amount: int
    status: InstallmentStatus

    model_config = {"from_attributes": True}


class LoanSummary(BaseModel):
    id: str
    customer_id: str
    customer_name: str
    collector_id: str
    collector_name: str
    principal: int
    interest_rate: float
    lending_model: LendingModel
    repayment_frequency: RepaymentFrequency
    total_installments: int
    installment_amount: int
    start_date: date
    status: LoanStatus
    outstanding: int
    repaid: int
    repaid_pct: float

    model_config = {"from_attributes": True}


class LoanDetail(LoanSummary):
    installments: list[InstallmentResponse]
