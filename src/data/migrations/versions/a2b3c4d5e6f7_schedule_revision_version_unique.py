"""one schedule revision per loan version

Guards the reschedule path at the database level: even if two concurrent
confirms slipped past the application row lock, the second would violate this
index instead of leaving the loan with two active replacement plans.

Revision ID: a2b3c4d5e6f7
Revises: f1a2b3c4d5e6
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a2b3c4d5e6f7"
down_revision: str | None = "f1a2b3c4d5e6"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_schedule_revisions_loan_version",
        "schedule_revisions",
        ["loan_id", "version"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_schedule_revisions_loan_version", "schedule_revisions", type_="unique"
    )
