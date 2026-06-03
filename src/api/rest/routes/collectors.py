"""Collector API routes."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.rest.dependencies import get_current_user, get_db
from src.core.services.collector_service import CollectorService
from src.schemas.collector import CollectorResponse

router = APIRouter(prefix="/collectors", tags=["collectors"])


@router.get("", response_model=list[CollectorResponse])
async def list_collectors(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CollectorResponse]:
    return await CollectorService(db).list(current_user)
