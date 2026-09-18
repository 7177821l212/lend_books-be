"""backfill payment allocations for pre-existing collections

Payments taken before `payment_allocations` existed carry no breakdown, so the
collection history would render them without the per-installment detail the new
schedule UI relies on. This replays each loan's collections in the order they
were taken, using the allocation rule the old code actually applied — start at
the installment the collector targeted (`payments.schedule_id`), fall back to
the earliest row still owing, then spill forward by sequence — and it
distributes each receipt across the `paid_amount` already recorded on those
rows, so the reconstruction reconciles with stored state instead of
reinterpreting history.

Installment `paid_amount`, payment amounts and collection dates are never
modified: this migration only adds the derived breakdown rows. It is idempotent
— payments that already have allocations are skipped.

Revision ID: f1a2b3c4d5e6
Revises: e4f5a6b7c8d9
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: str | None = "e4f5a6b7c8d9"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()

    loan_ids = [
        row[0]
        for row in conn.execute(
            sa.text(
                """
                SELECT DISTINCT p.loan_id
                FROM payments p
                WHERE p.is_missed = false
                  AND p.amount > 0
                  AND NOT EXISTS (
                      SELECT 1 FROM payment_allocations a WHERE a.payment_id = p.id
                  )
                """
            )
        )
    ]

    rows_to_insert: list[dict[str, object]] = []

    for loan_id in loan_ids:
        installments = list(
            conn.execute(
                sa.text(
                    """
                    SELECT id, paid_amount
                    FROM installments
                    WHERE loan_id = :loan_id AND is_active = true
                    ORDER BY sequence, due_date
                    """
                ),
                {"loan_id": loan_id},
            )
        )
        if not installments:
            continue
        # Capacity is each row's RECORDED paid_amount, not its due_amount. That
        # makes the reconstruction reconcile with stored state by construction and
        # keeps MISSED rows (paid_amount 0) out of the walk, matching the old
        # allocator, which never spilled onto a missed visit.
        capacity = [int(paid_amount) for _, paid_amount in installments]
        index_of = {inst_id: i for i, (inst_id, _) in enumerate(installments)}
        credited = [0] * len(installments)

        payments = conn.execute(
            sa.text(
                """
                SELECT p.id, p.amount, p.schedule_id,
                       EXISTS (
                           SELECT 1 FROM payment_allocations a WHERE a.payment_id = p.id
                       ) AS already_allocated
                FROM payments p
                WHERE p.loan_id = :loan_id AND p.is_missed = false AND p.amount > 0
                ORDER BY p.collected_at, p.id
                """
            ),
            {"loan_id": loan_id},
        )

        for payment_id, amount, schedule_id, already_allocated in payments:
            # Replay allocated payments too, so their consumed capacity still
            # shifts the ones that follow — just don't write them again.
            start = index_of.get(schedule_id) if schedule_id else None
            if start is None:
                start = next(
                    (i for i in range(len(capacity)) if credited[i] < capacity[i]),
                    len(capacity),
                )

            remaining = int(amount)
            for i in range(start, len(capacity)):
                if remaining <= 0:
                    break
                available = capacity[i] - credited[i]
                if available <= 0:
                    continue
                credit = min(remaining, available)
                credited[i] += credit
                remaining -= credit
                if not already_allocated:
                    rows_to_insert.append(
                        {
                            "id": str(uuid.uuid4()),
                            "payment_id": payment_id,
                            "installment_id": installments[i][0],
                            "amount": credit,
                        }
                    )

    if rows_to_insert:
        conn.execute(
            sa.text(
                """
                INSERT INTO payment_allocations
                    (id, payment_id, installment_id, amount, created_at, updated_at)
                VALUES (:id, :payment_id, :installment_id, :amount, now(), now())
                """
            ),
            rows_to_insert,
        )


def downgrade() -> None:
    # The backfilled rows are derived data; dropping them loses nothing that the
    # payments and installments tables don't already hold.
    op.execute("DELETE FROM payment_allocations")
