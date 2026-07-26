"""Object storage utilities — upload + URL generation.

Two backends, chosen automatically:

* **GCS** (production / Cloud Run) — private bucket + v4 signed URLs.
* **Local filesystem** (fallback) — used when GCS credentials cannot be
  resolved (e.g. local Docker dev without a service-account key or ADC). Files
  are written under ``settings.LOCAL_UPLOAD_DIR`` and served publicly from
  ``{settings.PUBLIC_BASE_URL}/files/<object_name>``.

Callers use the same API regardless of backend: ``upload_photo`` /
``save_bytes`` return an *object name* (e.g. ``photos/abc.jpg``) to persist in
the DB, and ``generate_signed_url`` turns that object name into a URL the client
can load directly.
"""
import logging
import os
import uuid
from datetime import datetime, timedelta

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
            google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
            _use_gcs = True
    except Exception as exc:  # noqa: BLE001 — any failure means "fall back to local"
        logger.warning("GCS unavailable (%s); using local filesystem storage", exc)
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
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(google.auth.transport.requests.Request())
    return storage.Client(credentials=creds), creds


def strip_gs_prefix(object_name: str) -> str:
    """Normalise a possible ``gs://bucket/path`` URI down to the bare object path."""
    if object_name.startswith("gs://"):
        # gs://bucket/dir/file -> dir/file
        return object_name.split("/", 3)[-1]
    return object_name


# --------------------------------------------------------------------------- #
# Local filesystem backend
# --------------------------------------------------------------------------- #
def _local_path(object_name: str) -> str:
    safe = strip_gs_prefix(object_name).lstrip("/")
    return os.path.join(settings.LOCAL_UPLOAD_DIR, safe)


def _save_local(object_name: str, content: bytes) -> None:
    path = _local_path(object_name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(content)
    logger.info("Saved object locally at %s", path)


def _local_url(object_name: str) -> str:
    base = settings.PUBLIC_BASE_URL.rstrip("/")
    return f"{base}/files/{strip_gs_prefix(object_name).lstrip('/')}"


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
        _save_local(object_name, content)
    return object_name


def upload_photo(content: bytes, content_type: str, prefix: str = "photos") -> str:
    """Store image bytes and return a generated object name, e.g. 'photos/abc.jpg'."""
    ext = _MIME_TO_EXT.get(content_type, ".jpg")
    object_name = f"{prefix}/{uuid.uuid4().hex}{ext}"
    return save_bytes(content, content_type, object_name)


def generate_signed_url(object_name: str, expiry_hours: int = 1) -> str:
    """Return a URL the client can load directly for a stored object.

    GCS backend → a time-limited v4 signed URL. Local backend → a public
    ``/files/...`` URL. Tolerates a legacy ``gs://bucket/...`` object name.
    """
    object_name = strip_gs_prefix(object_name)

    if not _gcs_available():
        return _local_url(object_name)

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
    """True when uploads are usable (either GCS or the local fallback)."""
    return True  # local fallback is always available


def get_gcs_path(customer_id: str, doc_type: str, filename: str) -> str:
    """Generate an object path for a customer document."""
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    safe_name = os.path.basename(filename).replace(" ", "_")
    return f"documents/{customer_id}/{doc_type}/{timestamp}_{safe_name}"


class GCSClient:
    """Legacy wrapper kept for backward compatibility. Routes through the
    unified storage layer, so it transparently uses the local fallback too."""

    def __init__(self, bucket_name: str) -> None:
        self.bucket_name = bucket_name

    def generate_signed_url(self, blob_name: str, expiration_hours: int = 24) -> str:
        return generate_signed_url(blob_name, expiration_hours)

    def upload_from_string(
        self, blob_name: str, content: bytes, content_type: str = "application/octet-stream"
    ) -> str:
        """Store bytes and return the object name (not a gs:// URI)."""
        return save_bytes(content, content_type, blob_name)

    def delete_blob(self, blob_name: str) -> None:
        if _gcs_available():
            client, _ = _client_and_credentials()
            client.bucket(self.bucket_name).blob(blob_name).delete()
            logger.info("Deleted gs://%s/%s", self.bucket_name, blob_name)
        else:
            path = _local_path(blob_name)
            if os.path.exists(path):
                os.remove(path)
                logger.info("Deleted local object %s", path)
