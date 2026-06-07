"""Reports + dashboard routes (investor only)."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.rest.dependencies import get_current_user, get_db
from src.core.services.dashboard_service import DashboardService
from src.core.services.report_service import ReportService
from src.schemas.dashboard import DashboardResponse, ReportsResponse

router = APIRouter(tags=["reports"])


@router.get("/dashboard", response_model=DashboardResponse)
async def dashboard(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DashboardResponse:
    return await DashboardService(db).overview(current_user)


@router.get("/reports", response_model=ReportsResponse)
async def reports(
    collector_id: str | None = Query(None),
    period: str | None = Query(None, enum=["week", "month", "year"]),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReportsResponse:
    return await ReportService(db).overview(current_user, collector_id=collector_id, period=period)
