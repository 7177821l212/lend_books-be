"""CustomerDocument — uploaded files attached to a customer (ID proof, address, etc.)."""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.data.models.postgres.base import Base, generate_uuid


class CustomerDocument(Base):
    __tablename__ = "customer_documents"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=generate_uuid)
    customer_id: Mapped[str] = mapped_column(
        String, ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    doc_type: Mapped[str] = mapped_column(String(50), nullable=False)
    file_url: Mapped[str] = mapped_column(String(500), nullable=False)
    uploaded_by: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    customer = relationship("Customer", back_populates="documents")
