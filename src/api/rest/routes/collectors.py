"""Collector API routes."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.rest.dependencies import get_current_user, get_db
from src.core.services.collector_service import CollectorService
from src.schemas.collector import CollectorCreate, CollectorResponse, CollectorUpdate

router = APIRouter(prefix="/collectors", tags=["collectors"])


@router.get("", response_model=list[CollectorResponse])
async def list_collectors(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CollectorResponse]:
    return await CollectorService(db).list(current_user)


@router.post("", response_model=CollectorResponse, status_code=status.HTTP_201_CREATED)
async def create_collector(
    body: CollectorCreate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CollectorResponse:
    return await CollectorService(db).create(current_user, body)


@router.get("/{collector_id}", response_model=CollectorResponse)
async def get_collector(
    collector_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CollectorResponse:
    return await CollectorService(db).get(current_user, collector_id)


@router.patch("/{collector_id}", response_model=CollectorResponse)
async def update_collector(
    collector_id: str,
    body: CollectorUpdate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CollectorResponse:
    return await CollectorService(db).update(current_user, collector_id, body)


@router.patch("/{collector_id}/deactivate", response_model=CollectorResponse)
async def deactivate_collector(
    collector_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CollectorResponse:
    return await CollectorService(db).deactivate(current_user, collector_id)
