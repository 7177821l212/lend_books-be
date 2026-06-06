"""loan terms + installment paid_amount

Revision ID: 2d154b9bc36c
Revises: 13bc02258d84
Create Date: 2026-06-03 02:44:31.763675

SAFE-MIGRATION pattern:
1. add new columns NULLABLE
2. backfill from existing data (derives Model A snapshot from `interest_rate`)
3. ALTER ... SET NOT NULL
4. drop legacy columns

This makes the migration safe to run on a populated database — existing loan
rows are interpreted as Model A (interest deducted up-front) with PCT interest
equal to the prior `interest_rate` column.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "2d154b9bc36c"
down_revision: Union[str, Sequence[str], None] = "13bc02258d84"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # installments — rename `amount` → `due_amount`, add `paid_amount`
    # ------------------------------------------------------------------
    op.add_column("installments", sa.Column("due_amount", sa.Integer(), nullable=True))
    op.add_column(
        "installments",
        sa.Column("paid_amount", sa.Integer(), nullable=True, server_default=sa.text("0")),
    )

    # Backfill: due_amount := amount (same semantic), paid_amount already defaulted to 0
    op.execute("UPDATE installments SET due_amount = amount")
    op.execute("UPDATE installments SET paid_amount = 0 WHERE paid_amount IS NULL")

    op.alter_column("installments", "due_amount", nullable=False)
    op.alter_column("installments", "paid_amount", nullable=False)

    # FK + legacy column cleanup
    op.drop_constraint(op.f("installments_loan_id_fkey"), "installments", type_="foreignkey")
    op.drop_constraint(op.f("installments_payment_id_fkey"), "installments", type_="foreignkey")
    op.create_foreign_key(
        "fk_installments_loan_id",
        "installments",
        "loans",
        ["loan_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_column("installments", "amount")
    op.drop_column("installments", "payment_id")

    # ------------------------------------------------------------------
    # loans — add term snapshot columns NULLABLE first, then backfill
    # ------------------------------------------------------------------
    op.add_column("loans", sa.Column("interest_type", sa.String(length=10), nullable=True))
    op.add_column(
        "loans", sa.Column("interest_value", sa.Numeric(precision=10, scale=2), nullable=True)
    )
    op.add_column("loans", sa.Column("disbursed", sa.Integer(), nullable=True))
    op.add_column("loans", sa.Column("repayable", sa.Integer(), nullable=True))
    op.add_column("loans", sa.Column("profit", sa.Integer(), nullable=True))
    op.add_column("loans", sa.Column("frequency_meta", sa.JSON(), nullable=True))
    op.add_column("loans", sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("loans", sa.Column("close_reason", sa.String(length=255), nullable=True))

    # Backfill: interpret existing rows as Model A + PCT interest.
    # interest_amount = round(principal * interest_rate / 100)
    # disbursed = principal - interest_amount; repayable = principal; profit = interest_amount.
    op.execute(
        """
        UPDATE loans
           SET interest_type  = 'pct',
               interest_value = interest_rate,
               profit         = CAST(ROUND(principal * interest_rate / 100.0) AS INTEGER),
               disbursed      = principal - CAST(ROUND(principal * interest_rate / 100.0) AS INTEGER),
               repayable      = principal
         WHERE interest_type IS NULL
        """
    )

    # Now enforce NOT NULL on the financial snapshot columns
    op.alter_column("loans", "interest_type", nullable=False)
    op.alter_column("loans", "interest_value", nullable=False)
    op.alter_column("loans", "disbursed", nullable=False)
    op.alter_column("loans", "repayable", nullable=False)
    op.alter_column("loans", "profit", nullable=False)

    # Indexes on FK columns for list queries
    op.create_index(op.f("ix_loans_collector_id"), "loans", ["collector_id"], unique=False)
    op.create_index(op.f("ix_loans_customer_id"), "loans", ["customer_id"], unique=False)

    # Drop legacy column last (replaced by interest_type + interest_value)
    op.drop_column("loans", "interest_rate")


def downgrade() -> None:
    # Re-add interest_rate, populate from interest_value (lossy for FIXED type),
    # then drop the snapshot columns.
    op.add_column(
        "loans",
        sa.Column(
            "interest_rate",
            sa.NUMERIC(precision=5, scale=2),
            autoincrement=False,
            nullable=True,
        ),
    )
    op.execute("UPDATE loans SET interest_rate = interest_value")
    op.alter_column("loans", "interest_rate", nullable=False)

    op.drop_index(op.f("ix_loans_customer_id"), table_name="loans")
    op.drop_index(op.f("ix_loans_collector_id"), table_name="loans")
    op.drop_column("loans", "close_reason")
    op.drop_column("loans", "closed_at")
    op.drop_column("loans", "frequency_meta")
    op.drop_column("loans", "profit")
    op.drop_column("loans", "repayable")
    op.drop_column("loans", "disbursed")
    op.drop_column("loans", "interest_value")
    op.drop_column("loans", "interest_type")

    op.add_column(
        "installments",
        sa.Column("payment_id", sa.VARCHAR(), autoincrement=False, nullable=True),
    )
    op.add_column(
        "installments", sa.Column("amount", sa.INTEGER(), autoincrement=False, nullable=True)
    )
    op.execute("UPDATE installments SET amount = due_amount")
    op.alter_column("installments", "amount", nullable=False)

    op.drop_constraint("fk_installments_loan_id", "installments", type_="foreignkey")
    op.create_foreign_key(
        op.f("installments_payment_id_fkey"),
        "installments",
        "payments",
        ["payment_id"],
        ["id"],
    )
    op.create_foreign_key(
        op.f("installments_loan_id_fkey"), "installments", "loans", ["loan_id"], ["id"]
    )
    op.drop_column("installments", "paid_amount")
    op.drop_column("installments", "due_amount")
