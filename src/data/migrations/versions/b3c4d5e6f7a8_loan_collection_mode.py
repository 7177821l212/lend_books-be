"""loan collection mode: schedule or balance

Adds the discriminator that lets a loan track what is owed WITHOUT an
installment schedule — a running total collected against the repayable amount,
the way a collector keeps a notebook.

Every existing loan is stamped `schedule` so nothing about live loans changes:
they keep their installments, allocations and reschedule history, and the code
paths that serve them are untouched. Only newly created loans use `balance`.

`total_installments` and `installment_amount` become nullable because a balance
loan has neither. Existing rows keep their values.

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b3c4d5e6f7a8"
down_revision: str | None = "a2b3c4d5e6f7"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "loans",
        sa.Column(
            "collection_mode",
            sa.String(length=20),
            nullable=False,
            server_default="schedule",
        ),
    )
    op.create_index("ix_loans_collection_mode", "loans", ["collection_mode"])
    op.alter_column("loans", "total_installments", existing_type=sa.Integer(), nullable=True)
    op.alter_column("loans", "installment_amount", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    # Balance loans have no installment counts, so restoring NOT NULL would fail
    # on them. Give them a placeholder first — they are being abandoned by the
    # downgrade anyway, and this keeps the migration reversible.
    op.execute(
        "UPDATE loans SET total_installments = 1 WHERE total_installments IS NULL"
    )
    op.execute(
        "UPDATE loans SET installment_amount = repayable WHERE installment_amount IS NULL"
    )
    op.alter_column("loans", "installment_amount", existing_type=sa.Integer(), nullable=False)
    op.alter_column("loans", "total_installments", existing_type=sa.Integer(), nullable=False)
    op.drop_index("ix_loans_collection_mode", table_name="loans")
    op.drop_column("loans", "collection_mode")
