"""Audit record for an investor-approved replacement of future schedule rows."""

from datetime import date

from sqlalchemy import Date, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.data.models.postgres.base import Base, TimestampMixin, generate_uuid


class ScheduleRevision(Base, TimestampMixin):
    __tablename__ = "schedule_revisions"
    __table_args__ = (
        UniqueConstraint("loan_id", "version", name="uq_schedule_revisions_loan_version"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    loan_id: Mapped[str] = mapped_column(
        String, ForeignKey("loans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by: Mapped[str] = mapped_column(
        String, ForeignKey("users.id"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
