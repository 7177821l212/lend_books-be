"""Payment service — collect a payment, mark a missed visit, list history."""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants.enums import (
    InstallmentStatus,
    LoanStatus,
    PaymentMode,
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

    async def collect(self, current_user: dict, body: CollectRequest) -> PaymentResponse:
        loan = await self._get_loan_with_rbac(current_user, body.loan_id)
        if loan.status != LoanStatus.ACTIVE.value:
            raise ConflictError(f"loan is {loan.status}; cannot collect")

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

    async def mark_missed(self, current_user: dict, body: MissedRequest) -> PaymentResponse:
        loan = await self._get_loan_with_rbac(current_user, body.loan_id)
        if loan.status != LoanStatus.ACTIVE.value:
            raise ConflictError(f"loan is {loan.status}; cannot mark missed")

        installment = await self.session.get(Installment, body.schedule_id)
        if installment is None or installment.loan_id != loan.id:
            raise NotFoundError("installment", body.schedule_id)
        if installment.status == InstallmentStatus.PAID.value:
            raise ConflictError("installment is already paid")
        installment.status = InstallmentStatus.MISSED.value

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
            await self.session.execute(select(func.count()).select_from(base.subquery()))
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

    async def my_day(self, current_user: dict, today: date | None = None) -> MyDayResponse:
        if current_user.get("role") != UserRole.COLLECTOR.value:
            raise ForbiddenError("only collectors have a 'My Day' view")
        today = today or datetime.now(timezone.utc).date()

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

        collected_today_row = await self.session.execute(
            select(func.coalesce(func.sum(Payment.amount), 0)).where(
                Payment.collector_id == current_user["sub"],
                Payment.is_missed.is_(False),
                func.date(Payment.collected_at) == today,
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
        loan = await self.session.get(Loan, loan_id)
        if loan is None:
            raise NotFoundError("loan", loan_id)
        role = current_user.get("role")
        if role == UserRole.INVESTOR.value:
            # Investors aren't expected to record collections, but if they do,
            # they can act on any loan
            return loan
        if role == UserRole.COLLECTOR.value and loan.collector_id == current_user["sub"]:
            return loan
        raise ForbiddenError("loan not assigned to you")

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
            loan.closed_at = datetime.now(timezone.utc)
            loan.close_reason = "Fully collected"
            await self.session.flush()
