"""Installment ORM model — one row per scheduled payment."""

from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.constants.enums import InstallmentStatus
from src.data.models.postgres.base import Base, TimestampMixin, generate_uuid


class Installment(Base, TimestampMixin):
    __tablename__ = "installments"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    loan_id: Mapped[str] = mapped_column(
        String, ForeignKey("loans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    due_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    paid_amount: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=InstallmentStatus.PENDING.value, nullable=False, index=True
    )

    loan = relationship("Loan", back_populates="installments")
