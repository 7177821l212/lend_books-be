"""Photo upload + signed-URL endpoints."""
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.rest.dependencies import get_current_user, get_db
from src.constants.enums import LoanStatus, UserRole
from src.config.settings import settings
from src.data.models.postgres.customer import Customer
from src.data.models.postgres.customer_document import CustomerDocument
from src.data.models.postgres.loan import Loan
from src.data.models.postgres.payment import Payment
from src.data.models.postgres.user import User
from src.utils import gcs

router = APIRouter(tags=["uploads"])

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_SIZE = 5 * 1024 * 1024  # 5 MB


def _matches_image_signature(content: bytes, content_type: str) -> bool:
    signatures = {
        "image/jpeg": lambda data: data.startswith(b"\xff\xd8\xff"),
        "image/png": lambda data: data.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/gif": lambda data: data.startswith((b"GIF87a", b"GIF89a")),
        "image/webp": lambda data: data.startswith(b"RIFF") and data[8:12] == b"WEBP",
    }
    return signatures[content_type](content)


def _require_bucket() -> None:
    # Storage is always available — GCS in production, local filesystem fallback
    # in dev — so this only guards against a misconfigured deployment.
    if not gcs.storage_configured():
        raise HTTPException(status_code=503, detail="Photo storage is not configured")


async def _can_view_object(
    db: AsyncSession, current_user: dict, object_name: str
) -> bool:
    """Require the object to be attached to a resource visible to the caller."""
    paths = (object_name, f"gs://{settings.GCS_BUCKET_NAME}/{object_name}")
    role = current_user.get("role")

    if role == UserRole.INVESTOR.value:
        queries = (
            select(User.id).where(User.photo_url.in_(paths)),
            select(Customer.id).where(Customer.photo_url.in_(paths)),
            select(Payment.id).where(Payment.proof_photo_url.in_(paths)),
            select(CustomerDocument.id).where(CustomerDocument.file_url.in_(paths)),
        )
    elif role == UserRole.COLLECTOR.value:
        collector_id = current_user["sub"]
        queries = (
            select(User.id).where(User.id == collector_id, User.photo_url.in_(paths)),
            select(Customer.id)
            .join(Loan, Loan.customer_id == Customer.id)
            .where(
                Customer.photo_url.in_(paths),
                Loan.collector_id == collector_id,
                Loan.status == LoanStatus.ACTIVE.value,
            ),
            select(Payment.id)
            .join(Loan, Loan.id == Payment.loan_id)
            .where(
                Payment.proof_photo_url.in_(paths),
                Loan.collector_id == collector_id,
            ),
            select(CustomerDocument.id)
            .join(Customer, Customer.id == CustomerDocument.customer_id)
            .join(Loan, Loan.customer_id == Customer.id)
            .where(
                CustomerDocument.file_url.in_(paths),
                Loan.collector_id == collector_id,
                Loan.status == LoanStatus.ACTIVE.value,
            ),
        )
    else:
        return False

    for query in queries:
        if (await db.execute(query.limit(1))).scalar_one_or_none() is not None:
            return True
    return False


@router.post("/upload/photo")
async def upload_photo(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Upload a photo to GCS. Returns object_name (store in DB) and a 1-hour signed_url."""
    _require_bucket()

    content_type = file.content_type or ""
    if content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="Only JPEG/PNG/WEBP images are allowed")

    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(status_code=400, detail="Image must be under 5 MB")
    if not _matches_image_signature(content, content_type):
        raise HTTPException(status_code=400, detail="Image contents do not match its type")

    object_name = gcs.upload_photo(content, content_type)
    signed_url = gcs.generate_signed_url(object_name, expiry_hours=1)

    return {"object_name": object_name, "signed_url": signed_url}


@router.get("/upload/signed-url")
async def get_signed_url(
    object_name: str = Query(..., alias="object_name", description="GCS object name, e.g. photos/abc.jpg"),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Generate a fresh 1-hour signed URL for any private GCS object."""
    _require_bucket()

    # Normalise legacy `gs://bucket/...` references (documents stored before the
    # unified storage layer) before validating the prefix allowlist.
    normalized = gcs.strip_gs_prefix(object_name)
    allowed_prefixes = ("photos/", "documents/")
    if not gcs.is_safe_object_name(normalized) or not any(
        normalized.startswith(prefix) for prefix in allowed_prefixes
    ):
        raise HTTPException(status_code=400, detail="Invalid object path")
    if not await _can_view_object(db, current_user, normalized):
        raise HTTPException(status_code=403, detail="You cannot access this file")

    signed_url = gcs.generate_signed_url(normalized, expiry_hours=1)
    return {"signed_url": signed_url}
