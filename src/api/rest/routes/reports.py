from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.rest.dependencies import get_current_user, get_db

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/overdue")
async def overdue_report(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from src.core.services.report_service import ReportService
    return await ReportService(db).overdue(current_user)


@router.get("/summary")
async def summary_report(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from src.core.services.report_service import ReportService
    return await ReportService(db).summary(current_user)
