"""Customer document service — list + upload to GCS."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import settings
from src.constants.enums import UserRole
from src.core.exceptions.base import ForbiddenError, NotFoundError
from src.data.models.postgres.customer import Customer
from src.data.models.postgres.customer_document import CustomerDocument
from src.schemas.customer import DocumentResponse, DocumentUploadRequest
from src.utils.gcs import GCSClient, get_gcs_path


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
        self, current_user: dict, customer_id: str, doc_type: str, file_content: bytes, filename: str
    ) -> DocumentResponse:
        if current_user.get("role") != UserRole.INVESTOR.value:
            raise ForbiddenError("only investor can upload customer documents")
        await self._must_view(current_user, customer_id)

        if not settings.GCS_BUCKET_NAME:
            raise ForbiddenError("document upload is not configured")

        gcs = GCSClient(settings.GCS_BUCKET_NAME)
        blob_path = get_gcs_path(customer_id, doc_type.strip(), filename)
        gcs.upload_from_string(blob_path, file_content, content_type="application/octet-stream")
        file_url = f"gs://{settings.GCS_BUCKET_NAME}/{blob_path}"

        doc = CustomerDocument(
            customer_id=customer_id,
            doc_type=doc_type.strip(),
            file_url=file_url,
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
