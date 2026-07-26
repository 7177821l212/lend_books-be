"""Photo upload + signed-URL endpoints."""
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from src.api.rest.dependencies import get_current_user
from src.utils import gcs

router = APIRouter(tags=["uploads"])

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_SIZE = 5 * 1024 * 1024  # 5 MB


def _require_bucket() -> None:
    # Storage is always available — GCS in production, local filesystem fallback
    # in dev — so this only guards against a misconfigured deployment.
    if not gcs.storage_configured():
        raise HTTPException(status_code=503, detail="Photo storage is not configured")


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

    object_name = gcs.upload_photo(content, content_type)
    signed_url = gcs.generate_signed_url(object_name, expiry_hours=1)

    return {"object_name": object_name, "signed_url": signed_url}


@router.get("/upload/signed-url")
async def get_signed_url(
    object_name: str = Query(..., alias="object_name", description="GCS object name, e.g. photos/abc.jpg"),
    current_user: dict = Depends(get_current_user),
) -> dict:
    """Generate a fresh 1-hour signed URL for any private GCS object."""
    _require_bucket()

    # Normalise legacy `gs://bucket/...` references (documents stored before the
    # unified storage layer) before validating the prefix allowlist.
    normalized = gcs.strip_gs_prefix(object_name)
    allowed_prefixes = ("photos/", "documents/")
    if not any(normalized.startswith(p) for p in allowed_prefixes):
        raise HTTPException(status_code=400, detail="Invalid object path")

    signed_url = gcs.generate_signed_url(normalized, expiry_hours=1)
    return {"signed_url": signed_url}
