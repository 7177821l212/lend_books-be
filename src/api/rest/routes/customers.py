"""Customer API routes."""

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.rest.dependencies import get_current_user, get_db
from src.core.services.customer_document_service import CustomerDocumentService
from src.core.services.customer_service import CustomerService
from src.schemas.common import PaginatedResponse
from src.schemas.customer import (
    BlacklistRequest,
    CustomerCreate,
    CustomerResponse,
    CustomerUpdate,
    DocumentResponse,
)

router = APIRouter(prefix="/customers", tags=["customers"])


@router.get("", response_model=PaginatedResponse[CustomerResponse])
async def list_customers(
    status: str | None = Query(None, enum=["active", "overdue", "blacklisted"]),
    search: str | None = Query(None, max_length=100),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PaginatedResponse[CustomerResponse]:
    return await CustomerService(db).list(current_user, status, search, page, page_size)


@router.post("", response_model=CustomerResponse, status_code=status.HTTP_201_CREATED)
async def create_customer(
    body: CustomerCreate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CustomerResponse:
    return await CustomerService(db).create(current_user, body)


@router.get("/{customer_id}", response_model=CustomerResponse)
async def get_customer(
    customer_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CustomerResponse:
    return await CustomerService(db).get(current_user, customer_id)


@router.patch("/{customer_id}", response_model=CustomerResponse)
async def update_customer(
    customer_id: str,
    body: CustomerUpdate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CustomerResponse:
    return await CustomerService(db).update(current_user, customer_id, body)


@router.post("/{customer_id}/blacklist", response_model=CustomerResponse)
async def blacklist_customer(
    customer_id: str,
    body: BlacklistRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CustomerResponse:
    return await CustomerService(db).blacklist(current_user, customer_id, body.reason)


@router.delete("/{customer_id}/blacklist", response_model=CustomerResponse)
async def unblacklist_customer(
    customer_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CustomerResponse:
    return await CustomerService(db).unblacklist(current_user, customer_id)


@router.get("/{customer_id}/documents", response_model=list[DocumentResponse])
async def list_documents(
    customer_id: str,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[DocumentResponse]:
    return await CustomerDocumentService(db).list(current_user, customer_id)


@router.post(
    "/{customer_id}/documents",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    customer_id: str,
    doc_type: str = Form(...),
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DocumentResponse:
    content = await file.read()
    return await CustomerDocumentService(db).create(
        current_user, customer_id, doc_type, content, file.filename or "document"
    )
