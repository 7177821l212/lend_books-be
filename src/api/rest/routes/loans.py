"""Loan API routes."""

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.rest.dependencies import get_current_user, get_db
from src.core.services.loan_service import LoanService
from src.schemas.common import PaginatedResponse
from src.schemas.loan import (
    AssignCollectorRequest,
    CloseLoanRequest,
    LoanCreate,
    LoanDetail,
    LoanSummary,
    ReschedulePreview,
    RescheduleRequest,
    ScheduleRevisionResponse,
)

router = APIRouter(prefix="/loans", tags=["loans"])


@router.get("", response_model=PaginatedResponse[LoanSummary])
async def list_loans(
    status: str | None = Query(None, enum=["active", "overdue", "closed", "cancelled"]),
    customer_id: str | None = Query(None),
    collector_id: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[LoanSummary]:
    return await LoanService(db).list(
        current_user, status, customer_id, collector_id, page, page_size
    )


@router.post("", response_model=LoanDetail, status_code=status.HTTP_201_CREATED)
async def create_loan(
    body: LoanCreate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LoanDetail:
    return await LoanService(db).create(current_user, body)


@router.get("/{loan_id}", response_model=LoanDetail)
async def get_loan(
    loan_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LoanDetail:
    return await LoanService(db).get(current_user, loan_id)


@router.post("/{loan_id}/close", response_model=LoanDetail)
async def close_loan(
    loan_id: str,
    body: CloseLoanRequest | None = None,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LoanDetail:
    return await LoanService(db).close(current_user, loan_id, body)


@router.post("/{loan_id}/assign", response_model=LoanDetail)
async def assign_collector(
    loan_id: str,
    body: AssignCollectorRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LoanDetail:
    return await LoanService(db).assign(current_user, loan_id, body)


@router.post("/{loan_id}/reschedule", response_model=LoanDetail)
async def reschedule_loan(
    loan_id: str,
    body: RescheduleRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LoanDetail:
    return await LoanService(db).reschedule(current_user, loan_id, body)


@router.post("/{loan_id}/reschedule/preview", response_model=ReschedulePreview)
async def preview_reschedule(
    loan_id: str,
    body: RescheduleRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReschedulePreview:
    """Dry-run a reschedule: returns old vs. new remaining rows, writes nothing."""
    return await LoanService(db).preview_reschedule(current_user, loan_id, body)


@router.get("/{loan_id}/revisions", response_model=list[ScheduleRevisionResponse])
async def list_schedule_revisions(
    loan_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ScheduleRevisionResponse]:
    return await LoanService(db).list_revisions(current_user, loan_id)
