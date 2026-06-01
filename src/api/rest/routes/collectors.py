from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.rest.dependencies import get_current_user, get_db

router = APIRouter(prefix="/collectors", tags=["collectors"])


@router.get("")
async def list_collectors(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list:
    from src.core.services.collector_service import CollectorService
    return await CollectorService(db).list(current_user)


@router.get("/my-day")
async def my_day(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    from src.core.services.collector_service import CollectorService
    return await CollectorService(db).my_day(current_user)
