from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.constants.enums import InstallmentStatus
from src.data.models.postgres.base import Base, TimestampMixin, generate_uuid


class Installment(Base, TimestampMixin):
    __tablename__ = "installments"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    loan_id: Mapped[str] = mapped_column(String, ForeignKey("loans.id"), nullable=False, index=True)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), default=InstallmentStatus.PENDING, nullable=False, index=True
    )
    payment_id: Mapped[str | None] = mapped_column(String, ForeignKey("payments.id"), nullable=True)

    loan = relationship("Loan", back_populates="installments")
    payment = relationship("Payment", foreign_keys=[payment_id])
