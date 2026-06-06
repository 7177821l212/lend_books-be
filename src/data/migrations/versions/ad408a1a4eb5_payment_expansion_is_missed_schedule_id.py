"""payment expansion is_missed schedule_id

Revision ID: ad408a1a4eb5
Revises: 320e8dedfeaf
Create Date: 2026-06-06 14:12:04.293390

Safe migration: add NOT NULL columns nullable first, backfill, then enforce.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "ad408a1a4eb5"
down_revision: Union[str, Sequence[str], None] = "320e8dedfeaf"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("payments", sa.Column("schedule_id", sa.String(), nullable=True))
    op.add_column(
        "payments",
        sa.Column("is_missed", sa.Boolean(), nullable=True, server_default=sa.text("false")),
    )
    op.add_column("payments", sa.Column("missed_reason", sa.String(length=255), nullable=True))

    # Backfill existing payment rows: not missed
    op.execute("UPDATE payments SET is_missed = false WHERE is_missed IS NULL")

    op.alter_column("payments", "is_missed", nullable=False)
    op.alter_column(
        "payments", "mode", existing_type=sa.VARCHAR(length=10), nullable=True
    )

    op.create_index(
        op.f("ix_payments_collected_at"), "payments", ["collected_at"], unique=False
    )
    op.create_index(
        op.f("ix_payments_collector_id"), "payments", ["collector_id"], unique=False
    )
    op.create_index(op.f("ix_payments_is_missed"), "payments", ["is_missed"], unique=False)
    op.create_index(
        op.f("ix_payments_schedule_id"), "payments", ["schedule_id"], unique=False
    )

    op.drop_constraint(op.f("payments_loan_id_fkey"), "payments", type_="foreignkey")
    op.create_foreign_key(
        "fk_payments_schedule_id",
        "payments",
        "installments",
        ["schedule_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_payments_loan_id_cascade",
        "payments",
        "loans",
        ["loan_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_payments_loan_id_cascade", "payments", type_="foreignkey")
    op.drop_constraint("fk_payments_schedule_id", "payments", type_="foreignkey")
    op.create_foreign_key(
        op.f("payments_loan_id_fkey"), "payments", "loans", ["loan_id"], ["id"]
    )
    op.drop_index(op.f("ix_payments_schedule_id"), table_name="payments")
    op.drop_index(op.f("ix_payments_is_missed"), table_name="payments")
    op.drop_index(op.f("ix_payments_collector_id"), table_name="payments")
    op.drop_index(op.f("ix_payments_collected_at"), table_name="payments")
    op.alter_column(
        "payments", "mode", existing_type=sa.VARCHAR(length=10), nullable=False
    )
    op.drop_column("payments", "missed_reason")
    op.drop_column("payments", "is_missed")
    op.drop_column("payments", "schedule_id")
