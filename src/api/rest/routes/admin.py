from fastapi import APIRouter, Depends

from src.api.rest.dependencies import get_current_user
from src.core.services.monitoring_service import get_metrics

router = APIRouter(tags=["admin"])


@router.get("/api/v1/admin/metrics")
async def metrics(current_user: dict = Depends(get_current_user)) -> dict:
    return await get_metrics()
