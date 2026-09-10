"""Reports service — overdue list + blacklisted + analytics with filters."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants.enums import InterestType, LoanStatus, UserRole
from src.core.exceptions.base import ForbiddenError
from src.data.models.postgres.customer import Customer
from src.data.models.postgres.installment import Installment
from src.data.models.postgres.loan import Loan
from src.data.models.postgres.user import User
from src.schemas.dashboard import (
    BlacklistedCustomerRow,
    OverdueLoanRow,
    ReportsResponse,
)
from src.utils.time import business_today


def _period_start(period: str | None) -> date | None:
    today = business_today()
    if period == "week":
        return today - timedelta(days=7)
    if period == "month":
        return today - timedelta(days=30)
    if period == "year":
        return today - timedelta(days=365)
    return None


class ReportService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def overview(
        self,
        current_user: dict,
        collector_id: str | None = None,
        period: str | None = None,
    ) -> ReportsResponse:
        if current_user.get("role") != UserRole.INVESTOR.value:
            raise ForbiddenError("only investor can view reports")

        since = _period_start(period)
        overdue_rows = await self._overdue(collector_id=collector_id)
        blacklisted = await self._blacklisted()
        interest_earned, avg_loan, avg_rate = await self._analytics(
            collector_id=collector_id, since=since
        )

        return ReportsResponse(
            overdue=overdue_rows,
            blacklisted=blacklisted,
            total_interest_earned=interest_earned,
            avg_loan_size=avg_loan,
            avg_interest_rate=avg_rate,
        )

    async def _overdue(self, collector_id: str | None = None) -> list[OverdueLoanRow]:
        q = (
            select(
                Loan.id.label("loan_id"),
                Loan.customer_id,
                Customer.name.label("customer_name"),
                Loan.collector_id,
                User.name.label("collector_name"),
                func.count(Installment.id).label("count"),
                func.coalesce(
                    func.sum(Installment.due_amount - Installment.paid_amount), 0
                ).label("amount"),
            )
            .join(Customer, Customer.id == Loan.customer_id)
            .join(User, User.id == Loan.collector_id)
            .join(Installment, Installment.loan_id == Loan.id)
            .where(
                Loan.status == LoanStatus.ACTIVE.value,
                Installment.status.in_(["overdue", "missed"]),
            )
            .group_by(
                Loan.id, Loan.customer_id, Customer.name, Loan.collector_id, User.name
            )
            .order_by(func.sum(Installment.due_amount - Installment.paid_amount).desc())
        )
        if collector_id:
            q = q.where(Loan.collector_id == collector_id)

        result = await self.session.execute(q)
        return [
            OverdueLoanRow(
                loan_id=r.loan_id,
                customer_id=r.customer_id,
                customer_name=r.customer_name,
                collector_id=r.collector_id,
                collector_name=r.collector_name,
                overdue_installments=int(r.count or 0),
                overdue_amount=int(r.amount or 0),
            )
            for r in result.all()
        ]

    async def _blacklisted(self) -> list[BlacklistedCustomerRow]:
        result = await self.session.execute(
            select(Customer).where(Customer.is_blacklisted.is_(True)).order_by(Customer.name)
        )
        return [
            BlacklistedCustomerRow(
                customer_id=c.id,
                name=c.name,
                phone=c.phone,
                reason=c.blacklist_reason,
            )
            for c in result.scalars()
        ]

    async def _analytics(
        self, collector_id: str | None = None, since: date | None = None
    ) -> tuple[int, int, float]:
        filters = []
        if collector_id:
            filters.append(Loan.collector_id == collector_id)
        if since:
            filters.append(Loan.start_date >= since)

        interest = (
            await self.session.execute(
                select(func.coalesce(func.sum(Loan.profit), 0)).where(*filters)
            )
        ).scalar_one()

        avg_principal = (
            await self.session.execute(
                select(func.coalesce(func.avg(Loan.principal), 0)).where(*filters)
            )
        ).scalar_one()

        avg_pct = (
            await self.session.execute(
                select(func.coalesce(func.avg(Loan.interest_value), 0)).where(
                    Loan.interest_type == InterestType.PCT.value,
                    *filters,
                )
            )
        ).scalar_one()

        return int(interest), int(avg_principal or 0), float(avg_pct or 0)
