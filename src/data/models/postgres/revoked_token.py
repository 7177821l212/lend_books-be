"""RevokedToken — tracks refresh token jtis that have been rotated or invalidated.

Each row represents a refresh token's unique `jti` claim that must no longer be
accepted. We store both the `jti` and the `user_id` so a logout-everywhere can
revoke an entire user's refresh tokens cheaply.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from src.data.models.postgres.base import Base


class RevokedToken(Base):
    __tablename__ = "revoked_tokens"

    jti: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    revoked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
