"""Loan service — create with schedule, list, get, close, assign collector."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.constants.enums import (
    OPEN_INSTALLMENT_STATUSES,
    CollectionMode,
    InstallmentStatus,
    InterestType,
    LendingModel,
    LoanStatus,
    RepaymentFrequency,
    RescheduleMode,
    UserRole,
)
from src.core.exceptions.base import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from src.core.services.loan_terms import (
    ScheduleRow,
    build_reschedule_plan,
    compute_terms,
    generate_schedule,
)
from src.data.models.postgres.customer import Customer
from src.data.models.postgres.installment import Installment
from src.data.models.postgres.loan import Loan
from src.data.models.postgres.payment import Payment
from src.data.models.postgres.schedule_revision import ScheduleRevision
from src.data.models.postgres.user import User
from src.schemas.common import PaginatedResponse
from src.schemas.loan import (
    AssignCollectorRequest,
    CloseLoanRequest,
    InstallmentResponse,
    LoanCreate,
    LoanDetail,
    LoanSummary,
    ReschedulePreview,
    RescheduleRequest,
    SchedulePreviewRow,
    ScheduleRevisionResponse,
)


class LoanService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ---------------- Public API ----------------

    async def create(self, current_user: dict, body: LoanCreate) -> LoanDetail:
        self._require_investor(current_user)

        customer = await self.session.get(Customer, body.customer_id)
        if customer is None or customer.is_deleted:
            raise NotFoundError("customer", body.customer_id)
        if customer.is_blacklisted:
            raise ConflictError("blacklisted customers cannot receive new loans")

        collector = await self.session.get(User, body.collector_id)
        if collector is None or collector.role != UserRole.COLLECTOR.value:
            raise NotFoundError("collector", body.collector_id)
        if not collector.is_active:
            raise ConflictError("collector is inactive")

        is_balance = body.collection_mode is CollectionMode.BALANCE
        try:
            terms = compute_terms(
                principal=body.principal,
                interest_type=InterestType(body.interest_type),
                interest_value=body.interest_value,
                lending_model=LendingModel(body.lending_model),
            )
            # A balance loan is only the money terms — principal, interest and
            # the total to collect. No schedule is generated, so there are no
            # installments to keep in step when collections come in.
            schedule_rows = []
            installment_base = None
            if is_balance and body.total_installments:
                # Guidance only: what a visit would collect if the customer kept
                # to an even pace. No rows are created and nothing enforces it —
                # the customer may pay any amount on any day.
                installment_base = max(1, terms.repayable // body.total_installments)
            if not is_balance:
                installment_base, _installment_max, schedule_rows = generate_schedule(
                    start_date=body.start_date,
                    frequency=RepaymentFrequency(body.repayment_frequency),
                    frequency_meta=body.frequency_meta,
                    total_installments=body.total_installments,
                    repayable=terms.repayable,
                )
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

        next_number = await self.session.execute(
            select(func.coalesce(func.max(Loan.loan_number), 0) + 1).where(
                Loan.customer_id == customer.id
            )
        )
        loan = Loan(
            loan_number=int(next_number.scalar_one()),
            customer_id=customer.id,
            collector_id=collector.id,
            principal=terms.principal,
            interest_type=terms.interest_type.value,
            interest_value=float(terms.interest_value),
            lending_model=terms.lending_model.value,
            disbursed=terms.disbursed,
            repayable=terms.repayable,
            profit=terms.profit,
            collection_mode=body.collection_mode.value,
            repayment_frequency=body.repayment_frequency,
            frequency_meta=body.frequency_meta,
            total_installments=body.total_installments,
            installment_amount=installment_base,
            start_date=body.start_date,
            status=LoanStatus.ACTIVE.value,
        )
        self.session.add(loan)
        await self.session.flush()

        for row in schedule_rows:
            self.session.add(
                Installment(
                    loan_id=loan.id,
                    sequence=row.sequence,
                    due_date=row.due_date,
                    due_amount=row.due_amount,
                    paid_amount=0,
                    status=InstallmentStatus.PENDING.value,
                )
            )
        await self.session.flush()
        loan = await self._fetch_loan(loan.id)
        return await self._to_detail(loan)

    async def list(
        self,
        current_user: dict,
        status_filter: str | None,
        customer_id: str | None,
        collector_id: str | None,
        page: int,
        page_size: int,
    ) -> PaginatedResponse[LoanSummary]:
        offset = (page - 1) * page_size

        base = (
            select(Loan)
            .join(Customer, Customer.id == Loan.customer_id)
            .join(User, User.id == Loan.collector_id)
        )

        conds = []
        if current_user.get("role") == UserRole.COLLECTOR.value:
            conds.append(Loan.collector_id == current_user["sub"])
        if customer_id:
            conds.append(Loan.customer_id == customer_id)
        if collector_id:
            conds.append(Loan.collector_id == collector_id)
        if status_filter:
            conds.append(Loan.status == status_filter)

        if conds:
            base = base.where(and_(*conds))

        count_q = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_q)).scalar_one()

        result = await self.session.execute(
            base.order_by(Loan.created_at.desc())
            .offset(offset)
            .limit(page_size)
            .options(selectinload(Loan.customer), selectinload(Loan.collector))
        )
        loans = list(result.scalars())

        items = [await self._to_summary(loan) for loan in loans]
        return PaginatedResponse[LoanSummary](
            items=items,
            total=int(total),
            page=page,
            page_size=page_size,
            has_next=offset + page_size < total,
        )

    async def get(self, current_user: dict, loan_id: str) -> LoanDetail:
        loan = await self._fetch_loan(loan_id)
        self._check_can_view(current_user, loan)
        return await self._to_detail(loan)

    async def close(
        self, current_user: dict, loan_id: str, body: CloseLoanRequest | None = None
    ) -> LoanDetail:
        self._require_investor(current_user)
        loan = await self._fetch_loan(loan_id)
        if loan.status == LoanStatus.CLOSED.value:
            raise ConflictError("loan already closed")
        loan.status = LoanStatus.CLOSED.value
        loan.closed_at = datetime.now(UTC)
        loan.close_reason = (
            body.reason.strip() if body and body.reason else "Closed early"
        )
        await self.session.flush()
        loan = await self._fetch_loan(loan.id)
        return await self._to_detail(loan)

    async def assign(
        self, current_user: dict, loan_id: str, body: AssignCollectorRequest
    ) -> LoanDetail:
        self._require_investor(current_user)
        loan = await self._fetch_loan(loan_id)
        collector = await self.session.get(User, body.collector_id)
        if collector is None or collector.role != UserRole.COLLECTOR.value:
            raise NotFoundError("collector", body.collector_id)
        if not collector.is_active:
            raise ConflictError("collector is inactive")
        loan.collector_id = collector.id
        await self.session.flush()
        loan = await self._fetch_loan(loan.id)
        return await self._to_detail(loan)

    async def reschedule(
        self, current_user: dict, loan_id: str, body: RescheduleRequest
    ) -> LoanDetail:
        """Replace only unpaid active rows; payment history remains immutable."""
        loan, open_rows, _remaining, plan = await self._plan_reschedule(
            current_user, loan_id, body
        )

        next_version = max(row.schedule_version for row in loan.installments) + 1
        self.session.add(
            ScheduleRevision(
                loan_id=loan.id,
                created_by=current_user["sub"],
                version=next_version,
                reason=body.reason.strip(),
                effective_from=plan[0].due_date,
            )
        )

        now = datetime.now(UTC)
        for row in open_rows:
            row.is_active = False
            row.replaced_at = now

        # New rows continue the numbering after every sequence the loan has ever
        # used, so a replaced row and its replacement never share a number.
        next_sequence = max(row.sequence for row in loan.installments) + 1
        for offset, row in enumerate(plan):
            self.session.add(
                Installment(
                    loan_id=loan.id,
                    sequence=next_sequence + offset,
                    due_date=row.due_date,
                    due_amount=row.due_amount,
                    paid_amount=0,
                    status=InstallmentStatus.PENDING.value,
                    is_active=True,
                    schedule_version=next_version,
                )
            )

        # Everything still active at this point is settled history (paid or
        # missed); the open rows were just deactivated above.
        settled_rows = sum(1 for row in loan.installments if row.is_active)
        loan.total_installments = settled_rows + len(plan)
        await self.session.flush()
        return await self.get(current_user, loan.id)

    async def preview_reschedule(
        self, current_user: dict, loan_id: str, body: RescheduleRequest
    ) -> ReschedulePreview:
        """Show old remaining schedule vs. proposed plan without writing anything."""
        _, open_rows, remaining, plan = await self._plan_reschedule(
            current_user, loan_id, body
        )
        current = [
            SchedulePreviewRow(
                sequence=row.sequence,
                due_date=row.due_date,
                due_amount=row.due_amount,
                paid_amount=row.paid_amount,
            )
            for row in open_rows
        ]
        proposed = [
            SchedulePreviewRow(
                sequence=index + 1, due_date=row.due_date, due_amount=row.due_amount
            )
            for index, row in enumerate(plan)
        ]
        return ReschedulePreview(
            remaining_balance=remaining,
            current=current,
            proposed=proposed,
            current_total=sum(row.due_amount - row.paid_amount for row in open_rows),
            proposed_total=sum(row.due_amount for row in plan),
            current_end_date=current[-1].due_date if current else None,
            proposed_end_date=proposed[-1].due_date if proposed else None,
        )

    async def list_revisions(
        self, current_user: dict, loan_id: str
    ) -> list[ScheduleRevisionResponse]:
        """Audit trail of every approved replacement plan, newest first."""
        loan = await self._fetch_loan(loan_id)
        self._check_can_view(current_user, loan)
        result = await self.session.execute(
            select(ScheduleRevision, User.name)
            .join(User, User.id == ScheduleRevision.created_by)
            .where(ScheduleRevision.loan_id == loan_id)
            .order_by(ScheduleRevision.version.desc())
        )
        return [
            ScheduleRevisionResponse(
                id=revision.id,
                loan_id=revision.loan_id,
                version=revision.version,
                reason=revision.reason,
                effective_from=revision.effective_from,
                created_by=revision.created_by,
                created_by_name=created_by_name or "",
                created_at=revision.created_at,
            )
            for revision, created_by_name in result.all()
        ]

    async def _plan_reschedule(
        self, current_user: dict, loan_id: str, body: RescheduleRequest
    ) -> tuple[Loan, list[Installment], int, list[ScheduleRow]]:
        """Shared validation for preview and commit.

        Returns the loan, the rows that would be replaced, the balance those rows
        still expect, and the replacement plan. Raises before any write happens.
        """
        self._require_investor(current_user)
        # Lock the loan row first: without it two concurrent confirms both read
        # the same open rows and each insert a full replacement plan, leaving two
        # active plans and roughly double the outstanding balance. The unique
        # index on (loan_id, version) is the second line of defence.
        await self.session.execute(
            select(Loan.id).where(Loan.id == loan_id).with_for_update()
        )
        loan = await self._fetch_loan(loan_id)
        if loan.status != LoanStatus.ACTIVE.value:
            raise ConflictError("only active loans can be rescheduled")
        if loan.collection_mode == CollectionMode.BALANCE.value:
            raise ConflictError(
                "this loan has no schedule to reschedule; the customer pays any "
                "amount against the remaining balance"
            )

        # MISSED rows are excluded deliberately: marking a visit missed already
        # appended a replacement row carrying that money, so replacing the missed
        # row too would reschedule the same rupees twice.
        open_rows = sorted(
            [
                row
                for row in loan.installments
                if row.is_active and row.status in OPEN_INSTALLMENT_STATUSES
            ],
            key=lambda row: (row.due_date, row.sequence),
        )
        if not open_rows:
            raise ConflictError("loan has no open installments to reschedule")
        remaining = sum(row.due_amount - row.paid_amount for row in open_rows)

        if body.mode is RescheduleMode.MANUAL:
            plan = [
                ScheduleRow(
                    sequence=index + 1, due_date=row.due_date, due_amount=row.due_amount
                )
                for index, row in enumerate(body.installments)
            ]
            proposed_total = sum(row.due_amount for row in plan)
            if proposed_total != remaining:
                raise ValidationError(
                    f"rescheduled total must equal the remaining balance ({remaining})"
                )
        else:
            try:
                plan = build_reschedule_plan(
                    mode=body.mode.value,
                    remaining=remaining,
                    open_due_dates=[row.due_date for row in open_rows],
                    first_due_date=body.start_date or open_rows[0].due_date,
                    frequency=RepaymentFrequency(loan.repayment_frequency),
                    frequency_meta=loan.frequency_meta,
                    installment_amount=body.installment_amount,
                )
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc

        if not plan:
            raise ValidationError("the replacement plan is empty")
        return loan, open_rows, remaining, plan

    # ---------------- Internals ----------------

    async def _fetch_loan(self, loan_id: str) -> Loan:
        # `populate_existing` forces a re-read of a loan already in the identity
        # map. Without it, a reschedule that has just inserted replacement rows
        # would hand back the stale `installments` collection loaded earlier in
        # the same request, and the new rows would be missing from the response.
        result = await self.session.execute(
            select(Loan)
            .where(Loan.id == loan_id)
            .options(
                selectinload(Loan.customer),
                selectinload(Loan.collector),
                selectinload(Loan.installments),
            )
            .execution_options(populate_existing=True)
        )
        loan = result.scalar_one_or_none()
        if loan is None:
            raise NotFoundError("loan", loan_id)
        return loan

    @staticmethod
    def _require_investor(current_user: dict) -> None:
        if current_user.get("role") != UserRole.INVESTOR.value:
            raise ForbiddenError("only investor can perform this action")

    @staticmethod
    def _check_can_view(current_user: dict, loan: Loan) -> None:
        if current_user.get("role") == UserRole.INVESTOR.value:
            return
        if loan.collector_id == current_user["sub"]:
            return
        raise ForbiddenError("loan not assigned to you")

    async def _to_summary(self, loan: Loan) -> LoanSummary:
        if loan.collection_mode == CollectionMode.BALANCE.value:
            outstanding, repaid, paid_count, overdue_count = await self._balance_aggregates(loan)
        else:
            outstanding, repaid, paid_count, overdue_count = await self._aggregates(loan.id)
        missed_count = await self._missed_count(loan.id)
        repaid_pct = round((repaid / loan.repayable) * 100, 1) if loan.repayable else 0

        # installment_amount is the BASE (floor) amount;
        # installment_amount_max is the largest single-installment value
        # (= base + 1 if `repayable % total_installments != 0`, else base).
        if loan.installment_amount is None or loan.total_installments is None:
            installment_amount_max = None  # balance loan — no per-visit amount
        else:
            remainder = loan.repayable - loan.installment_amount * loan.total_installments
            installment_amount_max = (
                loan.installment_amount + 1 if remainder > 0 else loan.installment_amount
            )

        return LoanSummary(
            id=loan.id,
            customer_id=loan.customer_id,
            customer_name=loan.customer.name if loan.customer else "",
            collector_id=loan.collector_id,
            collector_name=loan.collector.name if loan.collector else "",
            principal=loan.principal,
            interest_type=loan.interest_type,
            interest_value=float(loan.interest_value),
            lending_model=loan.lending_model,
            disbursed=loan.disbursed,
            repayable=loan.repayable,
            profit=loan.profit,
            collection_mode=loan.collection_mode,
            loan_number=loan.loan_number,
            missed_count=missed_count,
            repayment_frequency=loan.repayment_frequency,
            total_installments=loan.total_installments,
            installment_amount=loan.installment_amount,
            installment_amount_max=installment_amount_max,
            start_date=loan.start_date,
            status=loan.status,
            outstanding=outstanding,
            repaid=repaid,
            repaid_pct=repaid_pct,
            paid_count=paid_count,
            overdue_count=overdue_count,
            closed_at=loan.closed_at,
        )

    async def _to_detail(self, loan: Loan) -> LoanDetail:
        summary = await self._to_summary(loan)
        installments = sorted(
            loan.installments,
            key=lambda i: (i.due_date, i.sequence, i.schedule_version),
        )
        return LoanDetail(
            **summary.model_dump(),
            installments=[InstallmentResponse.model_validate(i) for i in installments],
        )

    async def _missed_count(self, loan_id: str) -> int:
        """Visits where the collector called and collected nothing."""
        result = await self.session.execute(
            select(func.count(Payment.id)).where(
                Payment.loan_id == loan_id, Payment.is_missed.is_(True)
            )
        )
        return int(result.scalar_one() or 0)

    async def _balance_aggregates(self, loan: Loan) -> tuple[int, int, int, int]:
        """Figures for a BALANCE loan, taken straight from the payment ledger.

        There is no schedule to consult: what was collected is the sum of the
        receipts, and what is left is simply the rest of the repayable amount.
        `paid_count` is the number of collections and `overdue_count` is always
        zero, because a balance loan has no due dates to fall behind.
        """
        result = await self.session.execute(
            select(
                func.coalesce(func.sum(Payment.amount), 0),
                func.count(Payment.id),
            ).where(Payment.loan_id == loan.id, Payment.is_missed.is_(False))
        )
        collected, count = result.one()
        repaid = int(collected or 0)
        return max(0, loan.repayable - repaid), repaid, int(count or 0), 0

    async def _aggregates(self, loan_id: str) -> tuple[int, int, int, int]:
        """Return (outstanding, repaid, paid_count, overdue_count) for a loan."""
        result = await self.session.execute(
            select(
                # A MISSED row was already compensated by an extra row appended
                # to the end of the schedule, so counting it here would bill the
                # same rupees twice.
                func.coalesce(
                    func.sum(Installment.due_amount - Installment.paid_amount).filter(
                        Installment.status.in_(OPEN_INSTALLMENT_STATUSES)
                    ),
                    0,
                ).label("outstanding"),
                func.count(Installment.id)
                .filter(Installment.status == InstallmentStatus.PAID.value)
                .label("paid_count"),
                func.count(Installment.id)
                .filter(
                    or_(
                        Installment.status == InstallmentStatus.OVERDUE.value,
                        Installment.status == InstallmentStatus.MISSED.value,
                    )
                )
                .label("overdue_count"),
            ).where(Installment.loan_id == loan_id, Installment.is_active.is_(True))
        )
        row = result.one()
        outstanding = max(0, int(row.outstanding or 0))

        # `repaid` is CASH COLLECTED, counted directly rather than derived as
        # `repayable - outstanding`. The derivation silently lost money whenever
        # the schedule's total drifted from `repayable` — a visit paid ₹1,100
        # and then marked missed reported ₹2,200 repaid instead of ₹3,300.
        # Every row counts here, including MISSED rows and rows a reschedule
        # replaced: they still hold cash the customer really handed over.
        repaid_row = await self.session.execute(
            select(func.coalesce(func.sum(Installment.paid_amount), 0)).where(
                Installment.loan_id == loan_id
            )
        )
        repaid = int(repaid_row.scalar_one() or 0)
        return (
            outstanding,
            repaid,
            int(row.paid_count or 0),
            int(row.overdue_count or 0),
        )
