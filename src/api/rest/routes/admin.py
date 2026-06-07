from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from pathlib import Path

from src.api.rest.dependencies import get_current_user
from src.core.services.monitoring_service import get_metrics

router = APIRouter(tags=["admin"])

_DASHBOARD_HTML = Path(__file__).resolve().parent.parent.parent.parent.parent / "static" / "dashboard.html"


@router.get("/admin/dashboard", response_class=HTMLResponse, include_in_schema=False)
async def cost_dashboard() -> str:
    return _DASHBOARD_HTML.read_text()


@router.get("/api/v1/admin/metrics")
async def metrics(current_user: dict = Depends(get_current_user)) -> dict:
    return await get_metrics()
