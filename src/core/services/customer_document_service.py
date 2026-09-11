"""Customer document service — list + upload via the unified storage layer."""

import mimetypes
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants.enums import UserRole
from src.core.exceptions.base import ForbiddenError, ValidationError
from src.data.models.postgres.customer_document import CustomerDocument
from src.schemas.customer import DocumentResponse
from src.utils import gcs


class CustomerDocumentService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(
        self, current_user: dict, customer_id: str
    ) -> list[DocumentResponse]:
        await self._must_view(current_user, customer_id)
        result = await self.session.execute(
            select(CustomerDocument)
            .where(CustomerDocument.customer_id == customer_id)
            .order_by(CustomerDocument.uploaded_at.desc())
        )
        return [DocumentResponse.model_validate(d) for d in result.scalars()]

    async def create(
        self,
        current_user: dict,
        customer_id: str,
        doc_type: str,
        file_content: bytes,
        filename: str,
    ) -> DocumentResponse:
        if current_user.get("role") != UserRole.INVESTOR.value:
            raise ForbiddenError("only investor can upload customer documents")
        await self._must_view(current_user, customer_id)

        normalized_doc_type = doc_type.strip()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 _-]{0,49}", normalized_doc_type):
            raise ValidationError(
                "document type may contain letters, numbers, spaces, hyphens, and "
                "underscores"
            )

        storage_doc_type = re.sub(r"[\s_]+", "-", normalized_doc_type).lower()
        object_name = gcs.get_gcs_path(customer_id, storage_doc_type, filename)
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        gcs.save_bytes(file_content, content_type, object_name)

        doc = CustomerDocument(
            customer_id=customer_id,
            doc_type=normalized_doc_type,
            file_url=object_name,
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
