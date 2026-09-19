"""store each loan's number within its customer

`loan_number` tells a collector which of a customer's loans they are looking
at — "Loan 1" is the one given first. Deriving it on read from
(start_date, created_at) order meant registering a back-dated loan silently
renumbered the others, so the label a collector wrote down yesterday pointed at
a different loan today. It is now assigned once, at creation.

Existing loans are numbered by the order they were given, oldest first.

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4d5e6f7a8b9"
down_revision: str | None = "b3c4d5e6f7a8"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "loans",
        sa.Column("loan_number", sa.Integer(), nullable=False, server_default="1"),
    )
    # Backfill in the order the loans were actually given.
    op.execute(
        """
        UPDATE loans SET loan_number = ranked.rn
        FROM (
            SELECT id, ROW_NUMBER() OVER (
                PARTITION BY customer_id ORDER BY start_date, created_at, id
            ) AS rn
            FROM loans
        ) AS ranked
        WHERE loans.id = ranked.id
        """
    )


def downgrade() -> None:
    op.drop_column("loans", "loan_number")
