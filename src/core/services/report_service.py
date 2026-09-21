"""Reports service — collections, blacklisted customers and analytics."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants.enums import InterestType, UserRole
from src.core.exceptions.base import ForbiddenError
from src.core.services.dashboard_service import DashboardService
from src.data.models.postgres.customer import Customer
from src.data.models.postgres.loan import Loan
from src.schemas.dashboard import (
    BlacklistedCustomerRow,
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
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> ReportsResponse:
        if current_user.get("role") != UserRole.INVESTOR.value:
            raise ForbiddenError("only investor can view reports")

        since = start_date or _period_start(period)
        range_start, range_end = DashboardService.resolve_range(since, end_date)
        blacklisted = await self._blacklisted()
        interest_earned, avg_loan, avg_rate = await self._analytics(
            collector_id=collector_id, since=range_start
        )
        dashboard = DashboardService(self.session)
        collection_summary = await dashboard.collection_summary(
            range_start, range_end, collector_id=collector_id
        )
        collection_trend = await dashboard.collection_trend(
            range_start, range_end, collector_id=collector_id
        )
        collector_performance = await dashboard.collector_performance(
            range_start, range_end
        )
        if collector_id:
            collector_performance = [
                collector
                for collector in collector_performance
                if collector.id == collector_id
            ]

        return ReportsResponse(
            blacklisted=blacklisted,
            collection_summary=collection_summary,
            collection_trend=collection_trend,
            collector_performance=collector_performance,
            total_interest_earned=interest_earned,
            avg_loan_size=avg_loan,
            avg_interest_rate=avg_rate,
        )

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
