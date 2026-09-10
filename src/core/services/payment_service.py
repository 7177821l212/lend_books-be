"""Payment service — collect a payment, mark a missed visit, list history."""

from __future__ import annotations

import calendar
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants.enums import (
    InstallmentStatus,
    LoanStatus,
    RepaymentFrequency,
    UserRole,
)
from src.core.exceptions.base import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from src.data.models.postgres.customer import Customer
from src.data.models.postgres.installment import Installment
from src.data.models.postgres.loan import Loan
from src.data.models.postgres.payment import Payment
from src.schemas.common import PaginatedResponse
from src.schemas.payment import (
    CollectRequest,
    MissedRequest,
    MyDayResponse,
    PaymentResponse,
    PickupItem,
)
from src.utils.time import business_today, utc_day_bounds


class PaymentService:
    """Handles collection entries (success + missed) and the collector day-view.

    Invariants:
      - A collector can only act on loans assigned to them.
      - When a payment fully covers all installments, the loan is marked CLOSED.
      - `paid_amount` on an installment never exceeds `due_amount`.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------
    # Collect
    # ------------------------------------------------------------------

    async def collect(
        self, current_user: dict, body: CollectRequest
    ) -> PaymentResponse:
        loan = await self._get_loan_with_rbac(current_user, body.loan_id)
        if loan.status != LoanStatus.ACTIVE.value:
            raise ConflictError(f"loan is {loan.status}; cannot collect")

        remaining_balance = await self._remaining_collectible_balance(loan.id)
        if body.amount > remaining_balance:
            raise ConflictError("payment exceeds the remaining loan balance")

        installment = await self._pick_installment(loan, body.schedule_id)
        outstanding_on_inst = installment.due_amount - installment.paid_amount
        if outstanding_on_inst <= 0:
            raise ConflictError("selected installment is already fully paid")

        # Cap the credit applied to this installment; backend never over-credits a row
        credit = min(body.amount, outstanding_on_inst)
        installment.paid_amount += credit
        installment.status = (
            InstallmentStatus.PAID.value
            if installment.paid_amount >= installment.due_amount
            else InstallmentStatus.PARTIAL.value
        )

        # Propagate any overpayment to subsequent open installments
        excess = body.amount - credit
        if excess > 0:
            await self._apply_excess_to_next(loan, installment.sequence, excess)

        payment = Payment(
            loan_id=loan.id,
            schedule_id=installment.id,
            collector_id=current_user["sub"],
            is_missed=False,
            amount=body.amount,
            mode=body.mode.value,
            notes=body.notes,
            proof_photo_url=body.proof_photo_url,
        )
        self.session.add(payment)
        await self.session.flush()

        await self._maybe_close_loan(loan)
        await self.session.refresh(payment)
        return PaymentResponse.model_validate(payment)

    # ------------------------------------------------------------------
    # Mark missed
    # ------------------------------------------------------------------

    async def mark_missed(
        self, current_user: dict, body: MissedRequest
    ) -> PaymentResponse:
        loan = await self._get_loan_with_rbac(current_user, body.loan_id)
        if loan.status != LoanStatus.ACTIVE.value:
            raise ConflictError(f"loan is {loan.status}; cannot mark missed")

        installment = await self.session.get(Installment, body.schedule_id)
        if installment is None or installment.loan_id != loan.id:
            raise NotFoundError("installment", body.schedule_id)
        if installment.status not in {
            InstallmentStatus.PENDING.value,
            InstallmentStatus.PARTIAL.value,
            InstallmentStatus.DUE_TODAY.value,
            InstallmentStatus.OVERDUE.value,
        }:
            raise ConflictError("installment cannot be marked missed")
        installment.status = InstallmentStatus.MISSED.value

        # Extend the loan schedule by adding one installment at the end
        await self._extend_schedule(loan, installment.due_amount)

        payment = Payment(
            loan_id=loan.id,
            schedule_id=installment.id,
            collector_id=current_user["sub"],
            is_missed=True,
            missed_reason=body.reason.strip(),
            amount=0,
            mode=None,
            notes=body.notes,
        )
        self.session.add(payment)
        await self.session.flush()
        await self.session.refresh(payment)
        return PaymentResponse.model_validate(payment)

    # ------------------------------------------------------------------
    # History
    # ------------------------------------------------------------------

    async def history(
        self,
        current_user: dict,
        collector_id: str | None,
        loan_id: str | None,
        page: int,
        page_size: int,
    ) -> PaginatedResponse[PaymentResponse]:
        offset = (page - 1) * page_size
        base = select(Payment)

        conds = []
        # Collectors only see their own history; investors can pass collector_id filter
        if current_user.get("role") == UserRole.COLLECTOR.value:
            conds.append(Payment.collector_id == current_user["sub"])
        elif collector_id:
            conds.append(Payment.collector_id == collector_id)
        if loan_id:
            conds.append(Payment.loan_id == loan_id)
        if conds:
            base = base.where(and_(*conds))

        total = (
            await self.session.execute(
                select(func.count()).select_from(base.subquery())
            )
        ).scalar_one()
        result = await self.session.execute(
            base.order_by(Payment.collected_at.desc()).offset(offset).limit(page_size)
        )
        items = [PaymentResponse.model_validate(p) for p in result.scalars()]

        return PaginatedResponse[PaymentResponse](
            items=items,
            total=int(total),
            page=page,
            page_size=page_size,
            has_next=offset + page_size < int(total),
        )

    # ------------------------------------------------------------------
    # My Day — pickups for the calling collector
    # ------------------------------------------------------------------

    async def my_day(
        self, current_user: dict, today: date | None = None
    ) -> MyDayResponse:
        if current_user.get("role") != UserRole.COLLECTOR.value:
            raise ForbiddenError("only collectors have a 'My Day' view")
        today = today or business_today()

        # Find pickups: installments where the loan is assigned to this collector
        # and the row is pending/partial/overdue and due_date <= today.
        result = await self.session.execute(
            select(Installment, Loan, Customer)
            .join(Loan, Loan.id == Installment.loan_id)
            .join(Customer, Customer.id == Loan.customer_id)
            .where(
                Loan.collector_id == current_user["sub"],
                Loan.status == LoanStatus.ACTIVE.value,
                Installment.due_date <= today,
                Installment.status.in_(
                    [
                        InstallmentStatus.PENDING.value,
                        InstallmentStatus.PARTIAL.value,
                        InstallmentStatus.DUE_TODAY.value,
                        InstallmentStatus.OVERDUE.value,
                    ]
                ),
            )
            .order_by(Installment.due_date, Installment.sequence)
        )
        rows = result.all()

        pickups: list[PickupItem] = []
        for inst, loan, cust in rows:
            pickups.append(
                PickupItem(
                    loan_id=loan.id,
                    customer_id=cust.id,
                    customer_name=cust.name,
                    customer_phone=cust.phone,
                    customer_location=cust.location,
                    schedule_id=inst.id,
                    sequence=inst.sequence,
                    due_date=inst.due_date,
                    due_amount=inst.due_amount - inst.paid_amount,
                    is_overdue=inst.due_date < today,
                )
            )

        target_total = sum(p.due_amount for p in pickups)
        overdue_count = sum(1 for p in pickups if p.is_overdue)

        day_start, day_end = utc_day_bounds(today)
        collected_today_row = await self.session.execute(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(
                Payment.collector_id == current_user["sub"],
                Payment.is_missed.is_(False),
                Payment.collected_at >= day_start,
                Payment.collected_at < day_end,
            )
        )
        collected_today = int(collected_today_row.scalar_one() or 0)

        return MyDayResponse(
            today=today,
            pickups=pickups,
            target_total=target_total,
            collected_today=collected_today,
            pickup_count=len(pickups),
            overdue_count=overdue_count,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _get_loan_with_rbac(self, current_user: dict, loan_id: str) -> Loan:
        result = await self.session.execute(
            select(Loan).where(Loan.id == loan_id).with_for_update()
        )
        loan = result.scalar_one_or_none()
        if loan is None:
            raise NotFoundError("loan", loan_id)
        role = current_user.get("role")
        if role == UserRole.INVESTOR.value:
            # Investors aren't expected to record collections, but if they do,
            # they can act on any loan
            return loan
        if (
            role == UserRole.COLLECTOR.value
            and loan.collector_id == current_user["sub"]
        ):
            return loan
        raise ForbiddenError("loan not assigned to you")

    async def _remaining_collectible_balance(self, loan_id: str) -> int:
        open_statuses = [
            InstallmentStatus.PENDING.value,
            InstallmentStatus.PARTIAL.value,
            InstallmentStatus.DUE_TODAY.value,
            InstallmentStatus.OVERDUE.value,
        ]
        result = await self.session.execute(
            select(
                func.coalesce(
                    func.sum(Installment.due_amount - Installment.paid_amount), 0
                )
            ).where(
                Installment.loan_id == loan_id,
                Installment.status.in_(open_statuses),
            )
        )
        return int(result.scalar_one() or 0)

    async def _pick_installment(
        self, loan: Loan, schedule_id: str | None
    ) -> Installment:
        """Resolve the installment a payment applies to.

        If `schedule_id` is provided, use it (after verifying it belongs to the loan).
        Otherwise, take the earliest installment that's not fully paid.
        """
        if schedule_id is not None:
            installment = await self.session.get(Installment, schedule_id)
            if installment is None or installment.loan_id != loan.id:
                raise NotFoundError("installment", schedule_id)
            return installment

        result = await self.session.execute(
            select(Installment)
            .where(
                Installment.loan_id == loan.id,
                or_(
                    Installment.status == InstallmentStatus.PENDING.value,
                    Installment.status == InstallmentStatus.PARTIAL.value,
                    Installment.status == InstallmentStatus.OVERDUE.value,
                    Installment.status == InstallmentStatus.DUE_TODAY.value,
                ),
            )
            .order_by(Installment.sequence)
            .limit(1)
        )
        next_open = result.scalar_one_or_none()
        if next_open is None:
            raise ValidationError("loan has no open installments")
        return next_open

    async def _maybe_close_loan(self, loan: Loan) -> None:
        """Close the loan when every installment is PAID."""
        result = await self.session.execute(
            select(func.count(Installment.id)).where(
                Installment.loan_id == loan.id,
                Installment.status != InstallmentStatus.PAID.value,
            )
        )
        unpaid = int(result.scalar_one() or 0)
        if unpaid == 0:
            loan.status = LoanStatus.CLOSED.value
            loan.closed_at = datetime.now(UTC)
            loan.close_reason = "Fully collected"
            await self.session.flush()

    async def _extend_schedule(self, loan: Loan, due_amount: int) -> None:
        """Add one extra installment at the end of the loan schedule."""
        result = await self.session.execute(
            select(Installment)
            .where(Installment.loan_id == loan.id)
            .order_by(Installment.sequence.desc())
            .limit(1)
        )
        last = result.scalar_one_or_none()
        if last is None:
            return
        next_date = _next_installment_date(
            last.due_date, loan.repayment_frequency, loan.frequency_meta
        )
        new_inst = Installment(
            loan_id=loan.id,
            sequence=last.sequence + 1,
            due_date=next_date,
            due_amount=due_amount,
            paid_amount=0,
            status=InstallmentStatus.PENDING.value,
        )
        self.session.add(new_inst)
        loan.total_installments += 1
        await self.session.flush()

    async def _apply_excess_to_next(
        self, loan: Loan, current_sequence: int, excess: int
    ) -> None:
        """Apply overpayment excess to the next open installments in sequence order."""
        result = await self.session.execute(
            select(Installment)
            .where(
                Installment.loan_id == loan.id,
                Installment.sequence > current_sequence,
                Installment.status.in_(
                    [
                        InstallmentStatus.PENDING.value,
                        InstallmentStatus.PARTIAL.value,
                        InstallmentStatus.OVERDUE.value,
                        InstallmentStatus.DUE_TODAY.value,
                    ]
                ),
            )
            .order_by(Installment.sequence)
        )
        next_insts = list(result.scalars())
        remaining = excess
        for inst in next_insts:
            if remaining <= 0:
                break
            available = inst.due_amount - inst.paid_amount
            credit = min(remaining, available)
            inst.paid_amount += credit
            inst.status = (
                InstallmentStatus.PAID.value
                if inst.paid_amount >= inst.due_amount
                else InstallmentStatus.PARTIAL.value
            )
            remaining -= credit
        if next_insts:
            await self.session.flush()


def _next_installment_date(last_date: date, frequency: str, meta: dict | None) -> date:
    """Compute the due_date one period after `last_date` for the given frequency."""
    try:
        freq = RepaymentFrequency(frequency)
    except ValueError:
        return last_date + timedelta(days=1)

    if freq == RepaymentFrequency.DAILY:
        return last_date + timedelta(days=1)
    if freq == RepaymentFrequency.WEEKLY:
        return last_date + timedelta(days=7)
    if freq == RepaymentFrequency.MONTHLY:
        return _add_months(last_date, 1)
    if freq == RepaymentFrequency.HALF_YEARLY:
        return _add_months(last_date, 6)
    if freq == RepaymentFrequency.YEARLY:
        return _add_months(last_date, 12)
    if freq == RepaymentFrequency.CUSTOM and meta and "interval_days" in meta:
        return last_date + timedelta(days=int(meta["interval_days"]))
    return last_date + timedelta(days=1)


def _add_months(d: date, months: int) -> date:
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)
