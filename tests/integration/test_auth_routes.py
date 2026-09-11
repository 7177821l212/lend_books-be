"""Integration tests for /auth/* endpoints."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants.enums import UserRole
from src.data.models.postgres.user import User
from src.utils.security import hash_password


async def _make_user(
    db: AsyncSession,
    email: str = "test@example.com",
    password: str = "secret123",
    role: UserRole = UserRole.INVESTOR,
    is_active: bool = True,
) -> User:
    user = User(
        email=email,
        name=email.split("@")[0],
        hashed_password=hash_password(password),
        role=role.value,
        is_active=is_active,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


@pytest.mark.integration
class TestLoginRoute:
    async def test_login_success_returns_tokens(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _make_user(db_session, email="owner@example.com", password="owner123")
        res = await client.post(
            "/api/v1/auth/login",
            json={"email": "owner@example.com", "password": "owner123"},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["token_type"] == "bearer"
        assert body["access_token"]
        assert body["refresh_token"]

    async def test_login_wrong_password_returns_401(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _make_user(db_session, email="owner@example.com", password="correct-pw")
        res = await client.post(
            "/api/v1/auth/login",
            json={"email": "owner@example.com", "password": "wrong-pw"},
        )
        assert res.status_code == 401

    async def test_login_unknown_user_returns_401(self, client: AsyncClient) -> None:
        res = await client.post(
            "/api/v1/auth/login",
            json={"email": "ghost@example.com", "password": "anything"},
        )
        assert res.status_code == 401

    async def test_login_inactive_user_returns_401(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _make_user(
            db_session, email="disabled@example.com", password="x123", is_active=False
        )
        res = await client.post(
            "/api/v1/auth/login",
            json={"email": "disabled@example.com", "password": "x123"},
        )
        assert res.status_code == 401

    async def test_login_invalid_email_returns_422(self, client: AsyncClient) -> None:
        res = await client.post(
            "/api/v1/auth/login",
            json={"email": "not-an-email", "password": "x"},
        )
        assert res.status_code == 422


@pytest.mark.integration
class TestMeRoute:
    async def test_me_with_valid_token_returns_user(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user = await _make_user(
            db_session, email="me@example.com", password="pw12345", role=UserRole.COLLECTOR
        )
        user.photo_url = "photos/collector-profile.jpg"
        await db_session.commit()
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": "me@example.com", "password": "pw12345"},
        )
        token = login.json()["access_token"]

        res = await client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
        )
        assert res.status_code == 200
        body = res.json()
        assert body["id"] == user.id
        assert body["email"] == "me@example.com"
        assert body["role"] == "collector"
        assert body["photo_url"] == "photos/collector-profile.jpg"

    async def test_me_without_token_returns_401(self, client: AsyncClient) -> None:
        res = await client.get("/api/v1/auth/me")
        assert res.status_code == 401

    async def test_me_can_update_its_own_profile_photo(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _make_user(db_session, email="photo@example.com", password="pw12345")
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": "photo@example.com", "password": "pw12345"},
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        res = await client.patch(
            "/api/v1/auth/me",
            headers=headers,
            json={"photo_url": "photos/profile.jpg"},
        )
        assert res.status_code == 200
        assert res.json()["photo_url"] == "photos/profile.jpg"

        invalid = await client.patch(
            "/api/v1/auth/me",
            headers=headers,
            json={"photo_url": "documents/not-a-profile.jpg"},
        )
        assert invalid.status_code == 422

    async def test_me_with_bad_token_returns_401(self, client: AsyncClient) -> None:
        res = await client.get(
            "/api/v1/auth/me", headers={"Authorization": "Bearer not.a.jwt"}
        )
        assert res.status_code == 401

    async def test_signed_url_requires_a_persisted_visible_object(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        user = await _make_user(db_session, email="file@example.com", password="pw12345")
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": user.email, "password": "pw12345"},
        )
        res = await client.get(
            "/api/v1/upload/signed-url",
            headers={"Authorization": f"Bearer {login.json()['access_token']}"},
            params={"object_name": "photos/not-attached-to-a-record.jpg"},
        )
        assert res.status_code == 403


@pytest.mark.integration
class TestRefreshRoute:
    async def test_refresh_rotates_tokens(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _make_user(db_session, email="r@example.com", password="pw12345")
        login = await client.post(
            "/api/v1/auth/login", json={"email": "r@example.com", "password": "pw12345"}
        )
        refresh = login.json()["refresh_token"]

        res = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
        assert res.status_code == 200
        body = res.json()
        assert body["access_token"]
        assert body["refresh_token"]
        # New tokens should not be identical to the originals
        assert body["refresh_token"] != refresh

    async def test_refresh_with_access_token_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _make_user(db_session, email="r2@example.com", password="pw12345")
        login = await client.post(
            "/api/v1/auth/login", json={"email": "r2@example.com", "password": "pw12345"}
        )
        access = login.json()["access_token"]

        res = await client.post("/api/v1/auth/refresh", json={"refresh_token": access})
        assert res.status_code == 401

    async def test_refresh_with_garbage_returns_401(self, client: AsyncClient) -> None:
        res = await client.post("/api/v1/auth/refresh", json={"refresh_token": "junk"})
        assert res.status_code == 401

    async def test_refresh_token_cannot_be_replayed_after_use(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A refresh token's jti is revoked the moment it is used to issue a new pair.
        Replaying the same refresh token must be rejected."""
        await _make_user(db_session, email="replay@example.com", password="pw12345")
        login = await client.post(
            "/api/v1/auth/login", json={"email": "replay@example.com", "password": "pw12345"}
        )
        original_refresh = login.json()["refresh_token"]

        # First refresh succeeds
        ok = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": original_refresh}
        )
        assert ok.status_code == 200

        # Replay of the SAME refresh token must now be rejected
        replay = await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": original_refresh}
        )
        assert replay.status_code == 401
        assert "revoked" in replay.json()["detail"].lower()

    async def test_password_change_invalidates_existing_refresh_tokens(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        await _make_user(db_session, email="change@example.com", password="old-password")
        login = await client.post(
            "/api/v1/auth/login",
            json={"email": "change@example.com", "password": "old-password"},
        )
        body = login.json()

        changed = await client.post(
            "/api/v1/auth/change-password",
            headers={"Authorization": f"Bearer {body['access_token']}"},
            json={"current_password": "old-password", "new_password": "new-password"},
        )
        assert changed.status_code == 204

        refreshed = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": body["refresh_token"]},
        )
        assert refreshed.status_code == 401
