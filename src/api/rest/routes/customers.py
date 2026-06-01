from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.rest.dependencies import get_current_user, get_db
from src.constants.enums import UserRole
from src.schemas.common import PaginatedResponse
from src.schemas.customer import BlacklistRequest, CustomerCreate, CustomerResponse, CustomerUpdate

router = APIRouter(prefix="/customers", tags=["customers"])


@router.get("", response_model=PaginatedResponse[CustomerResponse])
async def list_customers(
    status: str | None = Query(None, enum=["active", "overdue", "blacklisted"]),
    search: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[CustomerResponse]:
    from src.core.services.customer_service import CustomerService
    return await CustomerService(db).list(current_user, status, search, page, page_size)


@router.post("", response_model=CustomerResponse, status_code=201)
async def create_customer(
    body: CustomerCreate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CustomerResponse:
    from src.core.services.customer_service import CustomerService
    return await CustomerService(db).create(current_user, body)


@router.get("/{customer_id}", response_model=CustomerResponse)
async def get_customer(
    customer_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CustomerResponse:
    from src.core.services.customer_service import CustomerService
    return await CustomerService(db).get(current_user, customer_id)


@router.patch("/{customer_id}", response_model=CustomerResponse)
async def update_customer(
    customer_id: str,
    body: CustomerUpdate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CustomerResponse:
    from src.core.services.customer_service import CustomerService
    return await CustomerService(db).update(current_user, customer_id, body)


@router.post("/{customer_id}/blacklist", response_model=CustomerResponse)
async def blacklist_customer(
    customer_id: str,
    body: BlacklistRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CustomerResponse:
    from src.core.services.customer_service import CustomerService
    return await CustomerService(db).blacklist(current_user, customer_id, body.reason)
