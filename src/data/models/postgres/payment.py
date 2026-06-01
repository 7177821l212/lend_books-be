from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.constants.enums import PaymentMode
from src.data.models.postgres.base import Base, generate_uuid


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    loan_id: Mapped[str] = mapped_column(String, ForeignKey("loans.id"), nullable=False, index=True)
    collector_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    mode: Mapped[str] = mapped_column(String(10), default=PaymentMode.CASH, nullable=False)
    proof_photo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    loan = relationship("Loan", back_populates="payments")
    collector = relationship("User", foreign_keys=[collector_id])
