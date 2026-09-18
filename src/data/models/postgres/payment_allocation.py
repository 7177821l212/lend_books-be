"""Immutable link between one collection event and one scheduled installment."""

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.data.models.postgres.base import Base, TimestampMixin, generate_uuid


class PaymentAllocation(Base, TimestampMixin):
    __tablename__ = "payment_allocations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    payment_id: Mapped[str] = mapped_column(
        String, ForeignKey("payments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    installment_id: Mapped[str] = mapped_column(
        String, ForeignKey("installments.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)

    payment = relationship("Payment", back_populates="allocations")
    installment = relationship("Installment")
