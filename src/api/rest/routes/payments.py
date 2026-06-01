from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.rest.dependencies import get_current_user, get_db
from src.schemas.common import PaginatedResponse
from src.schemas.payment import CollectRequest, MissedRequest, PaymentResponse

router = APIRouter(prefix="/payments", tags=["payments"])


@router.post("/collect", response_model=PaymentResponse, status_code=201)
async def collect(
    body: CollectRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaymentResponse:
    from src.core.services.payment_service import PaymentService
    return await PaymentService(db).collect(current_user, body)


@router.post("/missed", status_code=204)
async def mark_missed(
    body: MissedRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    from src.core.services.payment_service import PaymentService
    await PaymentService(db).mark_missed(current_user, body)


@router.get("/history", response_model=PaginatedResponse[PaymentResponse])
async def payment_history(
    collector_id: str | None = Query(None),
    loan_id: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[PaymentResponse]:
    from src.core.services.payment_service import PaymentService
    return await PaymentService(db).history(current_user, collector_id, loan_id, page, page_size)
