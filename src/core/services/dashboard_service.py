"""Dashboard service — KPI aggregates + 30-day trend + collector leaderboard."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants.enums import LoanStatus, UserRole
from src.core.exceptions.base import ForbiddenError
from src.data.models.postgres.customer import Customer
from src.data.models.postgres.installment import Installment
from src.data.models.postgres.loan import Loan
from src.data.models.postgres.payment import Payment
from src.data.models.postgres.user import User
from src.schemas.dashboard import (
    CollectionSummary,
    CollectorPerformance,
    DashboardKPIs,
    DashboardResponse,
    TrendPoint,
)
from src.utils.time import business_day_expr, business_today, utc_day_bounds


class DashboardService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def overview(
        self,
        current_user: dict,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> DashboardResponse:
        if current_user.get("role") != UserRole.INVESTOR.value:
            raise ForbiddenError("only investor can view dashboard")

        range_start, range_end = self.resolve_range(start_date, end_date)
        kpis = await self._kpis()
        trend = await self.collection_trend(range_start, range_end)
        collection_summary = await self.collection_summary(range_start, range_end)
        leaderboard = await self.collector_performance(range_start, range_end)
        return DashboardResponse(
            kpis=kpis,
            trend_30d=trend,
            collection_summary=collection_summary,
            collector_performance=leaderboard,
        )

    @staticmethod
    def resolve_range(
        start_date: date | None, end_date: date | None
    ) -> tuple[date, date]:
        today = business_today()
        end = end_date or today
        start = start_date or (end - timedelta(days=29))
        if start > end:
            start, end = end, start
        return start, end

    # ----- KPIs -----

    async def _kpis(self) -> DashboardKPIs:
        today = business_today()
        day_start, day_end = utc_day_bounds(today)

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
                    Payment.collected_at >= day_start,
                    Payment.collected_at < day_end,
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
                select(func.coalesce(func.sum(Payment.amount), 0))
                .join(Loan, Loan.id == Payment.loan_id)
                # Cash comes from the PAYMENTS ledger, not installment rows: a
                # balance loan has no installments, so summing paid_amount made
                # its collections invisible and overstated the balance.
                .where(
                    Loan.status == LoanStatus.ACTIVE.value,
                    Payment.is_missed.is_(False),
                )
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
                    Installment.is_active.is_(True),
                    Installment.status.in_(["overdue", "missed"]),
                )
            )
        ).scalar_one()
        overdue_amount = (
            await self.session.execute(
                select(
                    func.coalesce(
                        func.sum(Installment.due_amount - Installment.paid_amount), 0
                    )
                )
                .join(Loan, Loan.id == Installment.loan_id)
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
            overdue_amount=max(0, int(overdue_amount)),
            active_customers=int(active_customers),
            total_customers=int(total_customers),
        )

    # ----- Trend -----

    async def collection_trend(
        self,
        start_date: date,
        end_date: date,
        collector_id: str | None = None,
    ) -> list[TrendPoint]:
        """Day-wise collections over the range, optionally for one collector."""
        period_start, _ = utc_day_bounds(start_date)
        _, period_end = utc_day_bounds(end_date)
        business_day = business_day_expr(Payment.collected_at)

        result = await self.session.execute(
            select(
                business_day.label("day"),
                func.coalesce(func.sum(Payment.amount), 0).label("amount"),
            )
            .where(
                Payment.is_missed.is_(False),
                Payment.collected_at >= period_start,
                Payment.collected_at < period_end,
                *([Payment.collector_id == collector_id] if collector_id else []),
            )
            .group_by(business_day)
        )
        by_day = {row.day: int(row.amount or 0) for row in result.all()}

        points: list[TrendPoint] = []
        days = (end_date - start_date).days + 1
        for i in range(days):
            d = start_date + timedelta(days=i)
            points.append(TrendPoint(day=d, amount=by_day.get(d, 0)))
        return points

    async def collection_summary(
        self, start_date: date, end_date: date, collector_id: str | None = None
    ) -> CollectionSummary:
        period_start, _ = utc_day_bounds(start_date)
        _, period_end = utc_day_bounds(end_date)
        filters = [
            Payment.is_missed.is_(False),
            Payment.collected_at >= period_start,
            Payment.collected_at < period_end,
        ]
        if collector_id:
            filters.append(Payment.collector_id == collector_id)

        result = await self.session.execute(
            select(
                func.coalesce(func.sum(Payment.amount), 0).label("total_collected"),
                func.count(Payment.id).label("total_payments"),
                func.coalesce(
                    func.sum(Payment.amount).filter(Payment.mode == "CASH"), 0
                ).label("cash_collected"),
                func.coalesce(
                    func.sum(Payment.amount).filter(Payment.mode == "UPI"), 0
                ).label("upi_collected"),
                func.coalesce(
                    func.sum(Payment.amount).filter(Payment.mode == "BANK"), 0
                ).label("bank_collected"),
                func.count(distinct(Payment.collector_id)).label("active_collectors"),
            ).where(*filters)
        )
        row = result.one()
        return CollectionSummary(
            start_date=start_date,
            end_date=end_date,
            total_collected=int(row.total_collected or 0),
            total_payments=int(row.total_payments or 0),
            cash_collected=int(row.cash_collected or 0),
            upi_collected=int(row.upi_collected or 0),
            bank_collected=int(row.bank_collected or 0),
            active_collectors=int(row.active_collectors or 0),
        )

    # ----- Collector performance -----

    async def collector_performance(
        self, start_date: date, end_date: date
    ) -> list[CollectorPerformance]:
        period_start, _ = utc_day_bounds(start_date)
        _, period_end = utc_day_bounds(end_date)
        business_day = business_day_expr(Payment.collected_at)
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
                func.coalesce(
                    func.count(distinct(business_day)).filter(
                        Payment.is_missed.is_(False)
                    ),
                    0,
                ).label("collection_days"),
                func.max(business_day).filter(Payment.is_missed.is_(False)).label(
                    "last_collection_date"
                ),
            )
            .select_from(User)
            .outerjoin(
                Payment,
                (Payment.collector_id == User.id)
                & (Payment.collected_at >= period_start)
                & (Payment.collected_at < period_end),
            )
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
                collection_days=int(row.collection_days or 0),
                average_per_day=(
                    int((row.collected or 0) / int(row.collection_days))
                    if int(row.collection_days or 0)
                    else 0
                ),
                last_collection_date=row.last_collection_date,
            )
            for row in result.all()
        ]
