"""Loan ORM model — supports Model A (deducted up-front) and Model B (added on top)."""

from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.constants.enums import (
    InterestType,
    LendingModel,
    LoanStatus,
    RepaymentFrequency,
)
from src.data.models.postgres.base import Base, TimestampMixin, generate_uuid


class Loan(Base, TimestampMixin):
    __tablename__ = "loans"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    customer_id: Mapped[str] = mapped_column(
        String, ForeignKey("customers.id"), nullable=False, index=True
    )
    collector_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)

    # Loan terms
    principal: Mapped[int] = mapped_column(Integer, nullable=False)
    interest_type: Mapped[str] = mapped_column(
        String(10), default=InterestType.PCT.value, nullable=False
    )
    interest_value: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)
    lending_model: Mapped[str] = mapped_column(
        String(20), default=LendingModel.MODEL_A.value, nullable=False
    )

    # Computed amounts (snapshot at creation)
    disbursed: Mapped[int] = mapped_column(Integer, nullable=False)
    repayable: Mapped[int] = mapped_column(Integer, nullable=False)
    profit: Mapped[int] = mapped_column(Integer, nullable=False)

    # Schedule
    repayment_frequency: Mapped[str] = mapped_column(
        String(20), default=RepaymentFrequency.DAILY.value, nullable=False
    )
    frequency_meta: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    total_installments: Mapped[int] = mapped_column(Integer, nullable=False)
    installment_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Lifecycle
    status: Mapped[str] = mapped_column(
        String(20), default=LoanStatus.ACTIVE.value, nullable=False, index=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    close_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Relationships
    customer = relationship("Customer", back_populates="loans")
    collector = relationship("User", back_populates="loans", foreign_keys=[collector_id])
    installments = relationship(
        "Installment", back_populates="loan", order_by="Installment.due_date", cascade="all, delete-orphan"
    )
    payments = relationship("Payment", back_populates="loan", cascade="all, delete-orphan")
