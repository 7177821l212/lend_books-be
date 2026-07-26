"""Make all ORM models discoverable by Alembic autogenerate."""

from src.data.models.postgres.base import Base, TimestampMixin, generate_uuid
from src.data.models.postgres.collector_location import CollectorLocation
from src.data.models.postgres.customer import Customer
from src.data.models.postgres.customer_document import CustomerDocument
from src.data.models.postgres.installment import Installment
from src.data.models.postgres.loan import Loan
from src.data.models.postgres.payment import Payment
from src.data.models.postgres.revoked_token import RevokedToken
from src.data.models.postgres.user import User

__all__ = [
    "Base",
    "CollectorLocation",
    "Customer",
    "CustomerDocument",
    "Installment",
    "Loan",
    "Payment",
    "RevokedToken",
    "TimestampMixin",
    "User",
    "generate_uuid",
]
