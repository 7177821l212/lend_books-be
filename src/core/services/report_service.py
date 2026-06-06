"""Reports service — overdue list + blacklisted + analytics."""

from __future__ import annotations

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


class ReportService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def overview(self, current_user: dict) -> ReportsResponse:
        if current_user.get("role") != UserRole.INVESTOR.value:
            raise ForbiddenError("only investor can view reports")

        overdue_rows = await self._overdue()
        blacklisted = await self._blacklisted()
        interest_earned, avg_loan, avg_rate = await self._analytics()

        return ReportsResponse(
            overdue=overdue_rows,
            blacklisted=blacklisted,
            total_interest_earned=interest_earned,
            avg_loan_size=avg_loan,
            avg_interest_rate=avg_rate,
        )

    async def _overdue(self) -> list[OverdueLoanRow]:
        result = await self.session.execute(
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

    async def _analytics(self) -> tuple[int, int, float]:
        # Total interest = sum of profits across all loans (closed yields full, active = pro-rated)
        # For a simple report, use the full snapshot (treating it as "potential interest")
        interest = (
            await self.session.execute(
                select(func.coalesce(func.sum(Loan.profit), 0))
            )
        ).scalar_one()

        avg_principal = (
            await self.session.execute(select(func.coalesce(func.avg(Loan.principal), 0)))
        ).scalar_one()

        # Average PCT-style interest only (FIXED amounts are not percentages)
        avg_pct = (
            await self.session.execute(
                select(func.coalesce(func.avg(Loan.interest_value), 0)).where(
                    Loan.interest_type == InterestType.PCT.value
                )
            )
        ).scalar_one()

        return int(interest), int(avg_principal or 0), float(avg_pct or 0)
