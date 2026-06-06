"""Payment — transaction log row for collections and missed visits."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.constants.enums import PaymentMode
from src.data.models.postgres.base import Base, generate_uuid


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    loan_id: Mapped[str] = mapped_column(
        String, ForeignKey("loans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    schedule_id: Mapped[str | None] = mapped_column(
        String, ForeignKey("installments.id", ondelete="SET NULL"), nullable=True, index=True
    )
    collector_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)

    # `is_missed=True` rows are missed-visit records and amount/mode are unused
    is_missed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    missed_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)

    amount: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    mode: Mapped[str | None] = mapped_column(String(10), nullable=True)
    proof_photo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    loan = relationship("Loan", back_populates="payments")
    collector = relationship("User", foreign_keys=[collector_id])
