"""payment allocations and versioned schedule revisions

Revision ID: e4f5a6b7c8d9
Revises: bf091404bce9
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e4f5a6b7c8d9"
down_revision: str | None = "bf091404bce9"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "installments",
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "installments",
        sa.Column("schedule_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column("installments", sa.Column("replaced_at", sa.DateTime(timezone=True)))
    op.create_index("ix_installments_is_active", "installments", ["is_active"])

    op.create_table(
        "payment_allocations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("payment_id", sa.String(), nullable=False),
        sa.Column("installment_id", sa.String(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["payment_id"], ["payments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["installment_id"], ["installments.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_payment_allocations_payment_id", "payment_allocations", ["payment_id"])
    op.create_index("ix_payment_allocations_installment_id", "payment_allocations", ["installment_id"])

    op.create_table(
        "schedule_revisions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("loan_id", sa.String(), nullable=False),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["loan_id"], ["loans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
    )
    op.create_index("ix_schedule_revisions_loan_id", "schedule_revisions", ["loan_id"])
    op.create_index("ix_schedule_revisions_created_by", "schedule_revisions", ["created_by"])


def downgrade() -> None:
    op.drop_index("ix_schedule_revisions_created_by", table_name="schedule_revisions")
    op.drop_index("ix_schedule_revisions_loan_id", table_name="schedule_revisions")
    op.drop_table("schedule_revisions")
    op.drop_index("ix_payment_allocations_installment_id", table_name="payment_allocations")
    op.drop_index("ix_payment_allocations_payment_id", table_name="payment_allocations")
    op.drop_table("payment_allocations")
    op.drop_index("ix_installments_is_active", table_name="installments")
    op.drop_column("installments", "replaced_at")
    op.drop_column("installments", "schedule_version")
    op.drop_column("installments", "is_active")
