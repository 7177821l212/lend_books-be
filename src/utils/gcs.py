"""Google Cloud Storage utilities for private uploaded objects.

All application uploads are stored in the configured GCS bucket. There is no
filesystem fallback: an unavailable bucket is a visible failure rather than a
silent write to ephemeral Cloud Run storage.
"""

import logging
import os
import uuid
from datetime import UTC, datetime, timedelta

from src.config.settings import settings

logger = logging.getLogger(__name__)

_MIME_TO_EXT: dict[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}

# Cache the backend decision so we don't probe credentials on every call.
_use_gcs: bool | None = None


def _gcs_available() -> bool:
    """Return True if a usable GCS backend (bucket + credentials) is configured.

    The result is cached for the process lifetime. A bucket name is required;
    credentials come from either a service-account key file or ADC.
    """
    global _use_gcs
    if _use_gcs is not None:
        return _use_gcs

    if not settings.GCS_BUCKET_NAME:
        _use_gcs = False
        return _use_gcs

    try:
        import google.auth

        if settings.GOOGLE_APPLICATION_CREDENTIALS:
            _use_gcs = True
        else:
            # Probe ADC — raises DefaultCredentialsError when unavailable.
            google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            _use_gcs = True
    except Exception as exc:  # noqa: BLE001 -- surface the failure to callers.
        logger.error("GCS is unavailable: %s", exc)
        _use_gcs = False
    return _use_gcs


def _client_and_credentials():
    """Return (storage.Client, credentials) for the GCS backend."""
    import google.auth
    import google.auth.transport.requests
    from google.cloud import storage

    if settings.GOOGLE_APPLICATION_CREDENTIALS:
        from google.oauth2 import service_account

        creds = service_account.Credentials.from_service_account_file(
            settings.GOOGLE_APPLICATION_CREDENTIALS,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        return storage.Client(credentials=creds), creds

    # ADC — Cloud Run / GCE
    creds, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    creds.refresh(google.auth.transport.requests.Request())
    return storage.Client(credentials=creds), creds


def strip_gs_prefix(object_name: str) -> str:
    """Normalise a possible ``gs://bucket/path`` URI down to the bare object path."""
    if object_name.startswith("gs://"):
        # gs://bucket/dir/file -> dir/file
        return object_name.split("/", 3)[-1]
    return object_name


def is_safe_object_name(object_name: str) -> bool:
    """Return whether an object name is a relative, non-traversing GCS path."""
    normalized = strip_gs_prefix(object_name)
    parts = normalized.split("/")
    return bool(normalized) and all(part not in {"", ".", ".."} for part in parts)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def save_bytes(content: bytes, content_type: str, object_name: str) -> str:
    """Persist raw bytes at an explicit object name. Returns the object name."""
    if _gcs_available():
        client, _ = _client_and_credentials()
        blob = client.bucket(settings.GCS_BUCKET_NAME).blob(object_name)
        blob.upload_from_string(content, content_type=content_type)
        logger.info("Uploaded to gs://%s/%s", settings.GCS_BUCKET_NAME, object_name)
    else:
        raise RuntimeError("GCS storage is unavailable")
    return object_name


def upload_photo(content: bytes, content_type: str, prefix: str = "photos") -> str:
    """Store image bytes and return a generated object name, e.g. 'photos/abc.jpg'."""
    ext = _MIME_TO_EXT.get(content_type, ".jpg")
    object_name = f"{prefix}/{uuid.uuid4().hex}{ext}"
    return save_bytes(content, content_type, object_name)


def generate_signed_url(object_name: str, expiry_hours: int = 1) -> str:
    """Return a URL the client can load directly for a stored object.

    Returns a time-limited GCS v4 signed URL. Tolerates a legacy
    ``gs://bucket/...`` object name.
    """
    object_name = strip_gs_prefix(object_name)

    if not _gcs_available():
        raise RuntimeError("GCS storage is unavailable")

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


def storage_configured() -> bool:
    """True when the configured GCS bucket and credentials are usable."""
    return _gcs_available()


def get_gcs_path(customer_id: str, doc_type: str, filename: str) -> str:
    """Generate an object path for a customer document."""
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    safe_name = os.path.basename(filename).replace(" ", "_")
    return f"documents/{customer_id}/{doc_type}/{timestamp}_{safe_name}"


class GCSClient:
    """Compatibility wrapper for the GCS-only storage layer."""

    def __init__(self, bucket_name: str) -> None:
        self.bucket_name = bucket_name

    def generate_signed_url(self, blob_name: str, expiration_hours: int = 24) -> str:
        return generate_signed_url(blob_name, expiration_hours)

    def upload_from_string(
        self,
        blob_name: str,
        content: bytes,
        content_type: str = "application/octet-stream",
    ) -> str:
        """Store bytes and return the object name (not a gs:// URI)."""
        return save_bytes(content, content_type, blob_name)

    def delete_blob(self, blob_name: str) -> None:
        if _gcs_available():
            client, _ = _client_and_credentials()
            client.bucket(self.bucket_name).blob(blob_name).delete()
            logger.info("Deleted gs://%s/%s", self.bucket_name, blob_name)
        else:
            raise RuntimeError("GCS storage is unavailable")
