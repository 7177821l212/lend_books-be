"""customer soft delete

Revision ID: c7e8f9a0b1c2
Revises: b1c2d3e4f5a6
Create Date: 2026-07-22 00:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c7e8f9a0b1c2"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "customers",
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "customers",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("customers", "deleted_at")
    op.drop_column("customers", "is_deleted")
