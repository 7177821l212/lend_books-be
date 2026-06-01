from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.constants.enums import LendingModel, LoanStatus, RepaymentFrequency
from src.data.models.postgres.base import Base, TimestampMixin, generate_uuid


class Loan(Base, TimestampMixin):
    __tablename__ = "loans"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    investor_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    customer_id: Mapped[str] = mapped_column(String, ForeignKey("customers.id"), nullable=False)
    collector_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)

    principal: Mapped[int] = mapped_column(Integer, nullable=False)
    interest_rate: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    lending_model: Mapped[str] = mapped_column(String(20), default=LendingModel.MODEL_A)
    repayment_frequency: Mapped[str] = mapped_column(String(20), default=RepaymentFrequency.DAILY)
    total_installments: Mapped[int] = mapped_column(Integer, nullable=False)
    installment_amount: Mapped[int] = mapped_column(Integer, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default=LoanStatus.ACTIVE, nullable=False, index=True)

    customer = relationship("Customer", back_populates="loans")
    collector = relationship("User", back_populates="loans", foreign_keys=[collector_id])
    installments = relationship("Installment", back_populates="loan", order_by="Installment.due_date")
    payments = relationship("Payment", back_populates="loan")
