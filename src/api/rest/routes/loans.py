from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.rest.dependencies import get_current_user, get_db
from src.schemas.loan import LoanCreate, LoanDetail, LoanSummary
from src.schemas.common import PaginatedResponse

router = APIRouter(prefix="/loans", tags=["loans"])


@router.get("", response_model=PaginatedResponse[LoanSummary])
async def list_loans(
    status: str | None = Query(None),
    customer_id: str | None = Query(None),
    collector_id: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[LoanSummary]:
    from src.core.services.loan_service import LoanService
    return await LoanService(db).list(current_user, status, customer_id, collector_id, page, page_size)


@router.post("", response_model=LoanDetail, status_code=201)
async def create_loan(
    body: LoanCreate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LoanDetail:
    from src.core.services.loan_service import LoanService
    return await LoanService(db).create(current_user, body)


@router.get("/{loan_id}", response_model=LoanDetail)
async def get_loan(
    loan_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LoanDetail:
    from src.core.services.loan_service import LoanService
    return await LoanService(db).get(current_user, loan_id)


@router.post("/{loan_id}/close", response_model=LoanDetail)
async def close_loan(
    loan_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LoanDetail:
    from src.core.services.loan_service import LoanService
    return await LoanService(db).close(current_user, loan_id)
