"""Dashboard service — KPI aggregates + 30-day trend + collector leaderboard."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants.enums import InterestType, LendingModel, LoanStatus, UserRole
from src.core.exceptions.base import ForbiddenError
from src.data.models.postgres.customer import Customer
from src.data.models.postgres.installment import Installment
from src.data.models.postgres.loan import Loan
from src.data.models.postgres.payment import Payment
from src.data.models.postgres.user import User
from src.schemas.dashboard import (
    CollectorPerformance,
    DashboardKPIs,
    DashboardResponse,
    TrendPoint,
)


class DashboardService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def overview(self, current_user: dict) -> DashboardResponse:
        if current_user.get("role") != UserRole.INVESTOR.value:
            raise ForbiddenError("only investor can view dashboard")

        kpis = await self._kpis()
        trend = await self._trend_last_30_days()
        leaderboard = await self._collector_performance()
        return DashboardResponse(
            kpis=kpis,
            trend_30d=trend,
            collector_performance=leaderboard,
        )

    # ----- KPIs -----

    async def _kpis(self) -> DashboardKPIs:
        today = datetime.now(timezone.utc).date()

        # Capital disbursed = sum of all loan.disbursed (closed + active)
        capital_disbursed = (
            await self.session.execute(select(func.coalesce(func.sum(Loan.disbursed), 0)))
        ).scalar_one()

        # Collected lifetime = sum of payment.amount where not missed
        collected_lifetime = (
            await self.session.execute(
                select(func.coalesce(func.sum(Payment.amount), 0)).where(
                    Payment.is_missed.is_(False)
                )
            )
        ).scalar_one()
        collected_today = (
            await self.session.execute(
                select(func.coalesce(func.sum(Payment.amount), 0)).where(
                    Payment.is_missed.is_(False),
                    func.date(Payment.collected_at) == today,
                )
            )
        ).scalar_one()

        # Active outstanding = sum of (repayable - paid_on_installments) for ACTIVE loans
        repayable_active = (
            await self.session.execute(
                select(func.coalesce(func.sum(Loan.repayable), 0)).where(
                    Loan.status == LoanStatus.ACTIVE.value
                )
            )
        ).scalar_one()
        paid_active = (
            await self.session.execute(
                select(func.coalesce(func.sum(Installment.paid_amount), 0))
                .join(Loan, Loan.id == Installment.loan_id)
                .where(Loan.status == LoanStatus.ACTIVE.value)
            )
        ).scalar_one()
        outstanding = max(0, int(repayable_active) - int(paid_active))

        # Profit realised:
        # - closed loans: their full profit is captured
        # - active loans: pro-rate by (paid / repayable)
        closed_profit = (
            await self.session.execute(
                select(func.coalesce(func.sum(Loan.profit), 0)).where(
                    Loan.status == LoanStatus.CLOSED.value
                )
            )
        ).scalar_one()
        # Active profit recognized so far = (paid_active / repayable_active) * total_active_profit
        active_total_profit = (
            await self.session.execute(
                select(func.coalesce(func.sum(Loan.profit), 0)).where(
                    Loan.status == LoanStatus.ACTIVE.value
                )
            )
        ).scalar_one()
        ratio = (int(paid_active) / int(repayable_active)) if int(repayable_active) else 0
        profit_realised = int(closed_profit) + int(int(active_total_profit) * ratio)

        active_loans = (
            await self.session.execute(
                select(func.count(Loan.id)).where(Loan.status == LoanStatus.ACTIVE.value)
            )
        ).scalar_one()
        closed_loans = (
            await self.session.execute(
                select(func.count(Loan.id)).where(Loan.status == LoanStatus.CLOSED.value)
            )
        ).scalar_one()

        # Overdue loans = any active loan with at least one OVERDUE/MISSED installment
        overdue_loans = (
            await self.session.execute(
                select(func.count(distinct(Loan.id)))
                .join(Installment, Installment.loan_id == Loan.id)
                .where(
                    Loan.status == LoanStatus.ACTIVE.value,
                    Installment.status.in_(["overdue", "missed"]),
                )
            )
        ).scalar_one()

        active_customers = (
            await self.session.execute(
                select(func.count(distinct(Loan.customer_id))).where(
                    Loan.status == LoanStatus.ACTIVE.value
                )
            )
        ).scalar_one()
        total_customers = (
            await self.session.execute(select(func.count(Customer.id)))
        ).scalar_one()

        return DashboardKPIs(
            capital_disbursed=int(capital_disbursed),
            outstanding=int(outstanding),
            collected_lifetime=int(collected_lifetime),
            collected_today=int(collected_today),
            profit_realised=int(profit_realised),
            active_loans=int(active_loans),
            closed_loans=int(closed_loans),
            overdue_loans=int(overdue_loans),
            active_customers=int(active_customers),
            total_customers=int(total_customers),
        )

    # ----- Trend -----

    async def _trend_last_30_days(self) -> list[TrendPoint]:
        today = datetime.now(timezone.utc).date()
        thirty_days_ago = today - timedelta(days=29)

        result = await self.session.execute(
            select(
                func.date(Payment.collected_at).label("day"),
                func.coalesce(func.sum(Payment.amount), 0).label("amount"),
            )
            .where(
                Payment.is_missed.is_(False),
                func.date(Payment.collected_at) >= thirty_days_ago,
                func.date(Payment.collected_at) <= today,
            )
            .group_by(func.date(Payment.collected_at))
        )
        by_day = {row.day: int(row.amount or 0) for row in result.all()}

        points: list[TrendPoint] = []
        for i in range(30):
            d = thirty_days_ago + timedelta(days=i)
            points.append(TrendPoint(day=d, amount=by_day.get(d, 0)))
        return points

    # ----- Collector performance -----

    async def _collector_performance(self) -> list[CollectorPerformance]:
        result = await self.session.execute(
            select(
                User.id,
                User.name,
                func.coalesce(
                    func.sum(Payment.amount).filter(Payment.is_missed.is_(False)), 0
                ).label("collected"),
                func.coalesce(
                    func.count(Payment.id).filter(Payment.is_missed.is_(True)), 0
                ).label("missed"),
                func.coalesce(func.count(Payment.id), 0).label("visits"),
            )
            .select_from(User)
            .outerjoin(Payment, Payment.collector_id == User.id)
            .where(User.role == UserRole.COLLECTOR.value, User.is_active.is_(True))
            .group_by(User.id, User.name)
            .order_by(func.sum(Payment.amount).desc().nullslast())
        )
        return [
            CollectorPerformance(
                id=row.id,
                name=row.name,
                collected=int(row.collected or 0),
                missed=int(row.missed or 0),
                visits=int(row.visits or 0),
            )
            for row in result.all()
        ]
