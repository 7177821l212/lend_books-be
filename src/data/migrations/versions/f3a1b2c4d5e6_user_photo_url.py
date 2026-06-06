"""Add photo_url to users table.

Revision ID: f3a1b2c4d5e6
Revises: ad408a1a4eb5
Create Date: 2026-06-06

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3a1b2c4d5e6"
down_revision: str | None = "ad408a1a4eb5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("photo_url", sa.String(1024), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "photo_url")
