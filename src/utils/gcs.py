"""Google Cloud Storage utilities for document uploads."""
import logging
from datetime import datetime, timedelta
from typing import Optional

from google.cloud import storage

logger = logging.getLogger(__name__)


class GCSClient:
    """Wrapper around Google Cloud Storage for document uploads."""

    def __init__(self, bucket_name: str) -> None:
        """Initialize GCS client with bucket name."""
        self.bucket_name = bucket_name
        self.client = storage.Client()
        self.bucket = self.client.bucket(bucket_name)

    def generate_signed_url(
        self, blob_name: str, expiration_hours: int = 24
    ) -> str:
        """Generate a signed URL for downloading a document.

        Args:
            blob_name: Path to the object in GCS
            expiration_hours: How long the URL is valid (default: 24 hours)

        Returns:
            Signed URL string
        """
        blob = self.bucket.blob(blob_name)
        url = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(hours=expiration_hours),
            method="GET",
        )
        return url

    def get_upload_url(self, blob_name: str, content_type: str) -> str:
        """Generate a signed URL for uploading a document.

        Args:
            blob_name: Path where the object will be stored in GCS
            content_type: MIME type of the file (e.g., 'application/pdf')

        Returns:
            Signed URL for PUT request
        """
        blob = self.bucket.blob(blob_name)
        url = blob.generate_signed_url(
            version="v4",
            expiration=timedelta(hours=1),
            method="PUT",
            content_type=content_type,
        )
        return url

    def upload_from_string(
        self, blob_name: str, content: bytes, content_type: str = "application/octet-stream"
    ) -> str:
        """Upload file content directly to GCS.

        Args:
            blob_name: Path in GCS
            content: File bytes
            content_type: MIME type

        Returns:
            GCS path (gs://bucket/blob_name)
        """
        blob = self.bucket.blob(blob_name)
        blob.upload_from_string(content, content_type=content_type)
        logger.info("Uploaded document to gs://%s/%s", self.bucket_name, blob_name)
        return f"gs://{self.bucket_name}/{blob_name}"

    def delete_blob(self, blob_name: str) -> None:
        """Delete a document from GCS."""
        blob = self.bucket.blob(blob_name)
        blob.delete()
        logger.info("Deleted document gs://%s/%s", self.bucket_name, blob_name)


def get_gcs_path(customer_id: str, doc_type: str, filename: str) -> str:
    """Generate a GCS path for a document.

    Args:
        customer_id: Customer UUID
        doc_type: Document type (e.g., 'id_proof', 'address_proof')
        filename: Original filename

    Returns:
        GCS blob path
    """
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    return f"documents/{customer_id}/{doc_type}/{timestamp}_{filename}"
