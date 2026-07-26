"""CollectorLocation — a collector's most recently reported live location.

One row per collector (upserted on every report), not a full history trail —
the app only needs "where is this collector right now."
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.data.models.postgres.base import Base, generate_uuid


class CollectorLocation(Base):
    __tablename__ = "collector_locations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    collector_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
