"""Google Cloud Storage utilities — upload and signed-URL generation."""
import logging
import uuid
from datetime import datetime, timedelta

import google.auth
import google.auth.transport.requests
from google.cloud import storage

from src.config.settings import settings

logger = logging.getLogger(__name__)

_MIME_TO_EXT: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def _client_and_credentials() -> tuple[storage.Client, google.auth.credentials.Credentials]:
    if settings.GOOGLE_APPLICATION_CREDENTIALS:
        from google.oauth2 import service_account
        creds = service_account.Credentials.from_service_account_file(
            settings.GOOGLE_APPLICATION_CREDENTIALS,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        return storage.Client(credentials=creds), creds

    # ADC — Cloud Run / GCE
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(google.auth.transport.requests.Request())
    return storage.Client(credentials=creds), creds


def upload_photo(content: bytes, content_type: str, prefix: str = "photos") -> str:
    """Upload image bytes to GCS (private). Returns the object name, e.g. 'photos/abc.jpg'."""
    ext = _MIME_TO_EXT.get(content_type, ".jpg")
    object_name = f"{prefix}/{uuid.uuid4().hex}{ext}"
    client, _ = _client_and_credentials()
    blob = client.bucket(settings.GCS_BUCKET_NAME).blob(object_name)
    blob.upload_from_string(content, content_type=content_type)
    logger.info("Uploaded photo to gs://%s/%s", settings.GCS_BUCKET_NAME, object_name)
    return object_name


def generate_signed_url(object_name: str, expiry_hours: int = 1) -> str:
    """Return a time-limited signed URL for a private GCS object."""
    client, creds = _client_and_credentials()
    blob = client.bucket(settings.GCS_BUCKET_NAME).blob(object_name)

    kwargs: dict = {
        "expiration": timedelta(hours=expiry_hours),
        "method": "GET",
        "version": "v4",
    }
    # ADC creds expose service_account_email + token for IAM signing
    if hasattr(creds, "service_account_email"):
        kwargs["service_account_email"] = creds.service_account_email
    if hasattr(creds, "token") and creds.token:
        kwargs["access_token"] = creds.token

    return blob.generate_signed_url(**kwargs)


def get_gcs_path(customer_id: str, doc_type: str, filename: str) -> str:
    """Generate a GCS blob path for a customer document."""
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return f"documents/{customer_id}/{doc_type}/{timestamp}_{filename}"


class GCSClient:
    """Legacy wrapper kept for backward compatibility."""

    def __init__(self, bucket_name: str) -> None:
        self.bucket_name = bucket_name
        self.client = storage.Client()
        self.bucket = self.client.bucket(bucket_name)

    def generate_signed_url(self, blob_name: str, expiration_hours: int = 24) -> str:
        return generate_signed_url(blob_name, expiration_hours)

    def upload_from_string(self, blob_name: str, content: bytes, content_type: str = "application/octet-stream") -> str:
        blob = self.bucket.blob(blob_name)
        blob.upload_from_string(content, content_type=content_type)
        logger.info("Uploaded to gs://%s/%s", self.bucket_name, blob_name)
        return f"gs://{self.bucket_name}/{blob_name}"

    def delete_blob(self, blob_name: str) -> None:
        self.bucket.blob(blob_name).delete()
        logger.info("Deleted gs://%s/%s", self.bucket_name, blob_name)
