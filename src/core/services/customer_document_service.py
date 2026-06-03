"""Customer document service — list + upload (URL-only for now)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants.enums import UserRole
from src.core.exceptions.base import ForbiddenError, NotFoundError
from src.data.models.postgres.customer import Customer
from src.data.models.postgres.customer_document import CustomerDocument
from src.schemas.customer import DocumentResponse, DocumentUploadRequest


class CustomerDocumentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self, current_user: dict, customer_id: str) -> list[DocumentResponse]:
        await self._must_view(current_user, customer_id)
        result = await self.session.execute(
            select(CustomerDocument)
            .where(CustomerDocument.customer_id == customer_id)
            .order_by(CustomerDocument.uploaded_at.desc())
        )
        return [DocumentResponse.model_validate(d) for d in result.scalars()]

    async def create(
        self, current_user: dict, customer_id: str, body: DocumentUploadRequest
    ) -> DocumentResponse:
        if current_user.get("role") != UserRole.INVESTOR.value:
            raise ForbiddenError("only investor can upload customer documents")
        await self._must_view(current_user, customer_id)

        doc = CustomerDocument(
            customer_id=customer_id,
            doc_type=body.doc_type.strip(),
            file_url=body.file_url.strip(),
            uploaded_by=current_user["sub"],
        )
        self.session.add(doc)
        await self.session.flush()
        await self.session.refresh(doc)
        return DocumentResponse.model_validate(doc)

    async def _must_view(self, current_user: dict, customer_id: str) -> None:
        # Delegate the existence + RBAC check to CustomerService.
        from src.core.services.customer_service import CustomerService

        await CustomerService(self.session).get(current_user, customer_id)
