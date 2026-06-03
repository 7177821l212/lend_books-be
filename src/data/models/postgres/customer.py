from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.constants.enums import RiskLevel
from src.data.models.postgres.base import Base, TimestampMixin, generate_uuid


class Customer(Base, TimestampMixin):
    __tablename__ = "customers"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    risk_level: Mapped[str] = mapped_column(String(20), default=RiskLevel.MEDIUM, nullable=False)
    is_blacklisted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    blacklist_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)

    loans = relationship("Loan", back_populates="customer")
    documents = relationship(
        "CustomerDocument",
        back_populates="customer",
        cascade="all, delete-orphan",
    )
