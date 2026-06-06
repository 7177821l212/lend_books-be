"""customer photo_url

Revision ID: b1c2d3e4f5a6
Revises: f3a1b2c4d5e6
Create Date: 2026-06-06 00:00:00.000000
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "b1c2d3e4f5a6"
down_revision = "f3a1b2c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("customers", sa.Column("photo_url", sa.String(1024), nullable=True))


def downgrade() -> None:
    op.drop_column("customers", "photo_url")
