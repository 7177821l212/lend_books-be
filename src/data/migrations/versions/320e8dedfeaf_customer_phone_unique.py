"""customer phone unique

Revision ID: 320e8dedfeaf
Revises: d93d2191915d
Create Date: 2026-06-06 13:54:02.358717

Safe migration:
1. Strip non-digit chars from existing phone values (normalize representation)
2. Create the unique index

If duplicate normalized phones already exist, the CREATE UNIQUE INDEX will fail
with a clear unique-violation message instructing manual cleanup. We intentionally
don't auto-merge customers — that's a data decision the operator must make.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "320e8dedfeaf"
down_revision: Union[str, Sequence[str], None] = "d93d2191915d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Normalize phones to digits-only so the unique constraint is meaningful.
    op.execute("UPDATE customers SET phone = REGEXP_REPLACE(phone, '[^0-9]', '', 'g')")
    op.create_index(op.f("ix_customers_phone"), "customers", ["phone"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_customers_phone"), table_name="customers")
