"""Photo upload endpoint — stores files in GCS, returns a public URL."""
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from google.cloud import storage

from src.api.rest.dependencies import get_current_user
from src.config.settings import settings

router = APIRouter(tags=["uploads"])

ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_SIZE = 5 * 1024 * 1024  # 5 MB


def _gcs_client() -> storage.Client:
    if settings.GOOGLE_APPLICATION_CREDENTIALS:
        return storage.Client.from_service_account_json(settings.GOOGLE_APPLICATION_CREDENTIALS)
    return storage.Client()  # falls back to ADC (Application Default Credentials)


@router.post("/upload/photo")
async def upload_photo(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
) -> dict:
    if not settings.GCS_BUCKET_NAME:
        raise HTTPException(status_code=503, detail="Photo storage is not configured")

    content_type = file.content_type or ""
    if content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="Only JPEG/PNG/WEBP images are allowed")

    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(status_code=400, detail="Image must be under 5 MB")

    suffix = Path(file.filename or "photo.jpg").suffix or ".jpg"
    object_name = f"photos/{uuid.uuid4().hex}{suffix}"

    client = _gcs_client()
    bucket = client.bucket(settings.GCS_BUCKET_NAME)
    blob = bucket.blob(object_name)
    blob.upload_from_string(content, content_type=content_type)
    blob.make_public()

    return {"url": blob.public_url}
