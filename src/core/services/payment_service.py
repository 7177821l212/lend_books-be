"""Payment service — collect a payment, mark a missed visit, list history."""

from __future__ import annotations

import calendar
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.constants.enums import (
    OPEN_INSTALLMENT_STATUSES,
    CollectionMode,
    InstallmentStatus,
    LoanStatus,
    RepaymentFrequency,
    UserRole,
)
from src.core.exceptions.base import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
)
from src.data.models.postgres.customer import Customer
from src.data.models.postgres.installment import Installment
from src.data.models.postgres.loan import Loan
from src.data.models.postgres.payment import Payment
from src.data.models.postgres.payment_allocation import PaymentAllocation
from src.schemas.common import PaginatedResponse
from src.schemas.payment import (
    CollectRequest,
    MissedRequest,
    MyDayResponse,
    PaymentAllocationResponse,
    PaymentResponse,
    PickupItem,
)
from src.utils.time import business_noon_utc, business_today, utc_day_bounds


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

        if loan.collection_mode == CollectionMode.BALANCE.value:
            return await self._collect_against_balance(current_user, loan, body)

        remaining_balance = await self._remaining_collectible_balance(loan.id)
        if body.amount > remaining_balance:
            raise ConflictError("payment exceeds the remaining loan balance")

        # `schedule_id` is validated as a staleness check on the caller's view of
        # the schedule, but it does NOT steer allocation: a receipt always clears
        # the oldest unpaid rows first, then carries forward as advance credit.
        if body.schedule_id is not None:
            selected = await self.session.get(Installment, body.schedule_id)
            if selected is None or selected.loan_id != loan.id or not selected.is_active:
                raise NotFoundError("installment", body.schedule_id)

        payment = Payment(
            loan_id=loan.id,
            schedule_id=None,
            collector_id=current_user["sub"],
            is_missed=False,
            amount=body.amount,
            mode=body.mode.value,
            notes=body.notes,
            proof_photo_url=body.proof_photo_url,
        )
        if body.collected_on is not None:
            payment.collected_at = business_noon_utc(body.collected_on)
        self.session.add(payment)
        await self.session.flush()

        allocations = await self._allocate_payment(loan, payment, body.amount)
        # Points at the oldest row this receipt touched — kept for continuity with
        # pre-allocation payments. `allocations` is the authoritative breakdown.
        payment.schedule_id = allocations[0].installment_id if allocations else None

        await self._maybe_close_loan(loan)
        await self.session.flush()
        return self._payment_response(payment, allocations)

    # ------------------------------------------------------------------
    # Collect — balance loans
    # ------------------------------------------------------------------

    async def _collect_against_balance(
        self, current_user: dict, loan: Loan, body: CollectRequest
    ) -> PaymentResponse:
        """Record a receipt against a loan that keeps no schedule.

        The notebook model: what is left is the repayable amount minus
        everything collected so far, so a receipt needs no allocation and
        touches no installment rows. The customer may pay any amount on any
        day — ₹500 one day and ₹5,000 the next — and the loan closes the moment
        the total collected reaches the total to collect.
        """
        collected = await self._total_collected(loan.id)
        remaining = loan.repayable - collected
        if body.amount > remaining:
            raise ConflictError(
                f"payment exceeds the remaining balance (₹{remaining:,} left)"
            )

        payment = Payment(
            loan_id=loan.id,
            schedule_id=None,
            collector_id=current_user["sub"],
            is_missed=False,
            amount=body.amount,
            mode=body.mode.value,
            notes=body.notes,
            proof_photo_url=body.proof_photo_url,
        )
        if body.collected_on is not None:
            payment.collected_at = business_noon_utc(body.collected_on)
        self.session.add(payment)
        await self.session.flush()

        if collected + body.amount >= loan.repayable:
            loan.status = LoanStatus.CLOSED.value
            loan.closed_at = datetime.now(UTC)
            loan.close_reason = "Fully collected"
        await self.session.flush()
        return self._payment_response(payment, [])

    async def _total_collected(self, loan_id: str) -> int:
        """Every rupee received against this loan, regardless of when."""
        result = await self.session.execute(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(
                Payment.loan_id == loan_id, Payment.is_missed.is_(False)
            )
        )
        return int(result.scalar_one() or 0)

    # ------------------------------------------------------------------
    # Mark missed
    # ------------------------------------------------------------------

    async def mark_missed(
        self, current_user: dict, body: MissedRequest
    ) -> PaymentResponse:
        loan = await self._get_loan_with_rbac(current_user, body.loan_id)
        if loan.status != LoanStatus.ACTIVE.value:
            raise ConflictError(f"loan is {loan.status}; cannot mark missed")

        if loan.collection_mode == CollectionMode.BALANCE.value:
            raise ConflictError(
                "this loan has no schedule, so there is no visit to mark missed"
            )

        installment = await self.session.get(Installment, body.schedule_id)
        # A replaced row keeps its old PENDING/PARTIAL status, so without the
        # `is_active` check a collector working from a stale pickup list could
        # mark one missed and have `_extend_schedule` append a phantom
        # installment for money the replacement plan already covers.
        if installment is None or installment.loan_id != loan.id or not installment.is_active:
            raise NotFoundError("installment", body.schedule_id)
        if installment.status not in OPEN_INSTALLMENT_STATUSES:
            raise ConflictError("installment cannot be marked missed")
        # "Missed" means the collector came away from TODAY's visit with
        # nothing. Taking ₹1,100 on a ₹2,200 visit and then calling that same
        # visit missed contradicts the receipt the customer is holding — and
        # under the carry-forward rule it would also shunt the shortfall to the
        # end of the schedule instead of leaving it owed on its own date.
        #
        # The test is deliberately "collected TODAY", not "paid_amount > 0": a
        # row can hold advance credit from an earlier lump sum and still be a
        # genuinely missed visit today.
        collected_today = await self._collected_today_for(installment.id)
        if collected_today > 0:
            raise ConflictError(
                f"₹{collected_today:,} was already collected on this installment "
                "today; record a short payment instead of a missed visit"
            )
        installment.status = InstallmentStatus.MISSED.value

        # Carry only what is STILL OWED on this visit to the end of the
        # schedule. Money already collected against it stays collected: pushing
        # the full `due_amount` would re-bill the customer for cash they have
        # already handed over (₹1,100 paid on a ₹2,200 visit became a ₹2,200
        # catch-up row, so they owed ₹1,100 more than the contract).
        await self._extend_schedule(
            loan, installment.due_amount - installment.paid_amount
        )

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
        # A missed visit moves no cash, so it carries no allocations.
        return self._payment_response(payment, [])

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
            base.options(
                selectinload(Payment.allocations).selectinload(PaymentAllocation.installment)
            )
            .order_by(Payment.collected_at.desc())
            .offset(offset)
            .limit(page_size)
        )
        items = [self._payment_response(p, list(p.allocations)) for p in result.scalars()]

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
                Loan.collection_mode == CollectionMode.SCHEDULE.value,
                Installment.is_active.is_(True),
                Installment.due_date <= today,
                Installment.status.in_(OPEN_INSTALLMENT_STATUSES),
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

        # Only scheduled dues count toward the day's target — see MyDayResponse.
        target_total = sum(p.due_amount for p in pickups)
        overdue_count = sum(1 for p in pickups if p.is_overdue)

        pickups.extend(await self._balance_pickups(current_user["sub"]))

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

    async def _balance_pickups(self, collector_id: str) -> list[PickupItem]:
        """Every active balance loan assigned to this collector.

        These loans have no due dates, so there is nothing to be "due today" —
        they simply stay on the round until the balance is cleared, and the
        amount shown is what is left rather than an amount expected today.
        """
        result = await self.session.execute(
            select(
                Loan,
                Customer,
                func.coalesce(
                    select(func.sum(Payment.amount))
                    .where(Payment.loan_id == Loan.id, Payment.is_missed.is_(False))
                    .correlate(Loan)
                    .scalar_subquery(),
                    0,
                ).label("collected"),
            )
            .join(Customer, Customer.id == Loan.customer_id)
            .where(
                Loan.collector_id == collector_id,
                Loan.status == LoanStatus.ACTIVE.value,
                Loan.collection_mode == CollectionMode.BALANCE.value,
            )
            .order_by(Customer.name)
        )
        return [
            PickupItem(
                loan_id=loan.id,
                customer_id=customer.id,
                customer_name=customer.name,
                customer_phone=customer.phone,
                customer_location=customer.location,
                collection_mode=CollectionMode.BALANCE,
                due_amount=max(0, loan.repayable - int(collected or 0)),
            )
            for loan, customer, collected in result.all()
        ]


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

    async def _collected_today_for(self, installment_id: str) -> int:
        """Cash allocated to this installment by a payment taken TODAY."""
        day_start, day_end = utc_day_bounds(business_today())
        result = await self.session.execute(
            select(func.coalesce(func.sum(PaymentAllocation.amount), 0))
            .join(Payment, Payment.id == PaymentAllocation.payment_id)
            .where(
                PaymentAllocation.installment_id == installment_id,
                Payment.is_missed.is_(False),
                Payment.collected_at >= day_start,
                Payment.collected_at < day_end,
            )
        )
        return int(result.scalar_one() or 0)

    async def _remaining_collectible_balance(self, loan_id: str) -> int:
        result = await self.session.execute(
            select(
                func.coalesce(
                    func.sum(Installment.due_amount - Installment.paid_amount), 0
                )
            ).where(
                Installment.loan_id == loan_id,
                Installment.is_active.is_(True),
                Installment.status.in_(OPEN_INSTALLMENT_STATUSES),
            )
        )
        return int(result.scalar_one() or 0)

    async def _maybe_close_loan(self, loan: Loan) -> None:
        """Close the loan once nothing collectible is left.

        MISSED rows are excluded on purpose: their shortfall was already moved
        to a catch-up row at the end of the schedule, so leaving them in this
        count would keep a fully repaid loan open forever.
        """
        result = await self.session.execute(
            select(func.count(Installment.id)).where(
                Installment.loan_id == loan.id,
                Installment.is_active.is_(True),
                Installment.status.in_(OPEN_INSTALLMENT_STATUSES),
            )
        )
        unpaid = int(result.scalar_one() or 0)
        if unpaid == 0:
            loan.status = LoanStatus.CLOSED.value
            loan.closed_at = datetime.now(UTC)
            loan.close_reason = "Fully collected"
            await self.session.flush()

    async def _extend_schedule(self, loan: Loan, due_amount: int) -> None:
        """Append one catch-up installment for `due_amount` still owed."""
        if due_amount <= 0:
            return  # the visit was already covered; there is nothing to move
        result = await self.session.execute(
            select(Installment)
            .where(Installment.loan_id == loan.id, Installment.is_active.is_(True))
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
            schedule_version=last.schedule_version,
        )
        self.session.add(new_inst)
        loan.total_installments += 1
        await self.session.flush()

    async def _allocate_payment(
        self, loan: Loan, payment: Payment, amount: int
    ) -> list[PaymentAllocation]:
        """Allocate one cash event oldest-first and retain every allocation."""
        result = await self.session.execute(
            select(Installment)
            .where(
                Installment.loan_id == loan.id,
                Installment.is_active.is_(True),
                Installment.status.in_(OPEN_INSTALLMENT_STATUSES),
            )
            .order_by(Installment.due_date, Installment.sequence)
        )
        open_installments = list(result.scalars())
        remaining = amount
        allocations: list[PaymentAllocation] = []
        for inst in open_installments:
            if remaining <= 0:
                break
            available = inst.due_amount - inst.paid_amount
            if available <= 0:
                continue  # never write a zero-rupee allocation row
            credit = min(remaining, available)
            inst.paid_amount += credit
            inst.status = (
                InstallmentStatus.PAID.value
                if inst.paid_amount >= inst.due_amount
                else InstallmentStatus.PARTIAL.value
            )
            remaining -= credit
            allocation = PaymentAllocation(
                payment_id=payment.id,
                installment_id=inst.id,
                amount=credit,
            )
            allocation.installment = inst
            self.session.add(allocation)
            allocations.append(allocation)
        if remaining:
            raise ConflictError("payment exceeds the remaining loan balance")
        await self.session.flush()
        return allocations

    @staticmethod
    def _payment_response(
        payment: Payment, allocations: list[PaymentAllocation]
    ) -> PaymentResponse:
        return PaymentResponse(
            id=payment.id,
            loan_id=payment.loan_id,
            schedule_id=payment.schedule_id,
            collector_id=payment.collector_id,
            is_missed=payment.is_missed,
            missed_reason=payment.missed_reason,
            amount=payment.amount,
            mode=payment.mode,
            notes=payment.notes,
            proof_photo_url=payment.proof_photo_url,
            collected_at=payment.collected_at,
            allocations=[
                PaymentAllocationResponse(
                    installment_id=allocation.installment_id,
                    sequence=allocation.installment.sequence,
                    due_date=allocation.installment.due_date,
                    amount=allocation.amount,
                )
                for allocation in allocations
                if allocation.installment is not None
            ],
        )


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
