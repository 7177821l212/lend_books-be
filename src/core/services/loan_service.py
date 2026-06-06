"""Loan service — create with schedule, list, get, close, assign collector."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.constants.enums import (
    InstallmentStatus,
    InterestType,
    LendingModel,
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
from src.core.services.loan_terms import compute_terms, generate_schedule
from src.data.models.postgres.customer import Customer
from src.data.models.postgres.installment import Installment
from src.data.models.postgres.loan import Loan
from src.data.models.postgres.user import User
from src.schemas.common import PaginatedResponse
from src.schemas.loan import (
    AssignCollectorRequest,
    CloseLoanRequest,
    InstallmentResponse,
    LoanCreate,
    LoanDetail,
    LoanSummary,
)


class LoanService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ---------------- Public API ----------------

    async def create(self, current_user: dict, body: LoanCreate) -> LoanDetail:
        self._require_investor(current_user)

        customer = await self.session.get(Customer, body.customer_id)
        if customer is None:
            raise NotFoundError("customer", body.customer_id)
        if customer.is_blacklisted:
            raise ConflictError("blacklisted customers cannot receive new loans")

        collector = await self.session.get(User, body.collector_id)
        if collector is None or collector.role != UserRole.COLLECTOR.value:
            raise NotFoundError("collector", body.collector_id)
        if not collector.is_active:
            raise ConflictError("collector is inactive")

        try:
            terms = compute_terms(
                principal=body.principal,
                interest_type=InterestType(body.interest_type),
                interest_value=body.interest_value,
                lending_model=LendingModel(body.lending_model),
            )
            installment_base, _installment_max, schedule_rows = generate_schedule(
                start_date=body.start_date,
                frequency=RepaymentFrequency(body.repayment_frequency),
                frequency_meta=body.frequency_meta,
                total_installments=body.total_installments,
                repayable=terms.repayable,
            )
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

        loan = Loan(
            customer_id=customer.id,
            collector_id=collector.id,
            principal=terms.principal,
            interest_type=terms.interest_type.value,
            interest_value=float(terms.interest_value),
            lending_model=terms.lending_model.value,
            disbursed=terms.disbursed,
            repayable=terms.repayable,
            profit=terms.profit,
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

        base = select(Loan).join(Customer, Customer.id == Loan.customer_id).join(
            User, User.id == Loan.collector_id
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
        loan.closed_at = datetime.now(timezone.utc)
        loan.close_reason = body.reason.strip() if body and body.reason else "Closed early"
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

    # ---------------- Internals ----------------

    async def _fetch_loan(self, loan_id: str) -> Loan:
        result = await self.session.execute(
            select(Loan)
            .where(Loan.id == loan_id)
            .options(
                selectinload(Loan.customer),
                selectinload(Loan.collector),
                selectinload(Loan.installments),
            )
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
        outstanding, repaid, paid_count, overdue_count = await self._aggregates(loan.id)
        repaid_pct = round((repaid / loan.repayable) * 100, 1) if loan.repayable else 0

        # installment_amount is the BASE (floor) amount;
        # installment_amount_max is the largest single-installment value
        # (= base + 1 if `repayable % total_installments != 0`, else base).
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
        installments = sorted(loan.installments, key=lambda i: i.sequence)
        return LoanDetail(
            **summary.model_dump(),
            installments=[InstallmentResponse.model_validate(i) for i in installments],
        )

    async def _aggregates(self, loan_id: str) -> tuple[int, int, int, int]:
        """Return (outstanding, repaid, paid_count, overdue_count) for a loan."""
        result = await self.session.execute(
            select(
                func.coalesce(func.sum(Installment.paid_amount), 0).label("repaid"),
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
            ).where(Installment.loan_id == loan_id)
        )
        row = result.one()
        repaid = int(row.repaid or 0)
        # Outstanding = repayable - repaid (from loan)
        loan = await self.session.get(Loan, loan_id)
        outstanding = max(0, (loan.repayable if loan else 0) - repaid)
        return outstanding, repaid, int(row.paid_count or 0), int(row.overdue_count or 0)
