"""Reports + dashboard routes (investor only)."""

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.rest.dependencies import get_current_user, get_db
from src.core.services.dashboard_service import DashboardService
from src.core.services.report_service import ReportService
from src.schemas.dashboard import DashboardResponse, ReportsResponse

router = APIRouter(tags=["reports"])


@router.get("/dashboard", response_model=DashboardResponse)
async def dashboard(
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DashboardResponse:
    return await DashboardService(db).overview(
        current_user, start_date=start_date, end_date=end_date
    )


@router.get("/reports", response_model=ReportsResponse)
async def reports(
    collector_id: str | None = Query(None),
    period: str | None = Query(None, enum=["week", "month", "year"]),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReportsResponse:
    return await ReportService(db).overview(
        current_user,
        collector_id=collector_id,
        period=period,
        start_date=start_date,
        end_date=end_date,
    )
