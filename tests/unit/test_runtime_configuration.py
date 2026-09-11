"""Unit tests for production configuration and object-path safety."""

import pytest
from pydantic import ValidationError

from src.api.rest.routes.uploads import _matches_image_signature
from src.config.settings import Settings
from src.utils import gcs
from src.utils.gcs import is_safe_object_name


def test_production_accepts_deployed_environment_aliases() -> None:
    settings = Settings(
        _env_file=None,
        APP_ENV="production",
        DATABASE_URL="postgresql+asyncpg://user:password@db/lendbook",
        JWT_SECRET="a-real-secret",
        GCS_BUCKET="lendbook-photos",
    )

    assert settings.JWT_SECRET_KEY == "a-real-secret"
    assert settings.GCS_BUCKET_NAME == "lendbook-photos"


@pytest.mark.parametrize(
    "values",
    [
        {},
        {"DATABASE_URL": "postgresql+asyncpg://user:password@db/lendbook"},
        {
            "DATABASE_URL": "postgresql+asyncpg://user:password@db/lendbook",
            "JWT_SECRET": "dummy",
            "GCS_BUCKET": "lendbook-photos",
        },
    ],
)
def test_production_rejects_missing_or_placeholder_configuration(
    values: dict[str, str],
) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, APP_ENV="production", **values)


@pytest.mark.parametrize(
    ("object_name", "expected"),
    [
        ("photos/customer.jpg", True),
        ("documents/customer/id-proof.pdf", True),
        ("photos/../.env", False),
        ("/photos/customer.jpg", False),
        ("photos//customer.jpg", False),
    ],
)
def test_object_names_cannot_traverse_storage(
    object_name: str, expected: bool
) -> None:
    assert is_safe_object_name(object_name) is expected


def test_storage_never_falls_back_to_the_local_filesystem(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gcs, "_use_gcs", False)

    with pytest.raises(RuntimeError, match="GCS storage is unavailable"):
        gcs.save_bytes(b"file", "application/pdf", "documents/customer/id.pdf")


@pytest.mark.parametrize(
    ("content_type", "content", "expected"),
    [
        ("image/jpeg", b"\xff\xd8\xffrest", True),
        ("image/png", b"\x89PNG\r\n\x1a\nrest", True),
        ("image/webp", b"RIFFxxxxWEBPrest", True),
        ("image/jpeg", b"not-an-image", False),
        ("image/png", b"\xff\xd8\xffjpeg", False),
    ],
)
def test_upload_content_must_match_declared_image_type(
    content_type: str, content: bytes, expected: bool
) -> None:
    assert _matches_image_signature(content, content_type) is expected
