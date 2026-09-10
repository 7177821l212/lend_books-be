"""Integration tests for collector live-location permissions and freshness data."""

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants.enums import UserRole
from src.data.models.postgres.user import User
from src.utils.security import hash_password


async def _make_user(db: AsyncSession, email: str, role: UserRole) -> User:
    user = User(
        email=email,
        name=email.split("@")[0],
        hashed_password=hash_password("pw12345"),
        role=role.value,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


async def _login(client: AsyncClient, user: User) -> dict[str, str]:
    response = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "pw12345"}
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.mark.integration
class TestCollectorLocations:
    async def test_collector_location_is_visible_to_investor_with_server_time(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        investor = await _make_user(db_session, "inv-location@x.com", UserRole.INVESTOR)
        collector = await _make_user(
            db_session, "col-location@x.com", UserRole.COLLECTOR
        )
        collector_headers = await _login(client, collector)

        response = await client.post(
            "/api/v1/collectors/me/location",
            headers=collector_headers,
            json={
                "latitude": 11.0168,
                "longitude": 76.9558,
                "accuracy": 12.4,
                "recorded_at": (datetime.now(UTC) - timedelta(days=7)).isoformat(),
            },
        )
        assert response.status_code == 204

        investor_headers = await _login(client, investor)
        locations = await client.get(
            "/api/v1/collectors/locations", headers=investor_headers
        )
        assert locations.status_code == 200
        body = locations.json()
        assert len(body) == 1
        assert body[0]["collector_id"] == collector.id
        assert body[0]["latitude"] == pytest.approx(11.0168)
        assert body[0]["longitude"] == pytest.approx(76.9558)
        recorded_at = datetime.fromisoformat(
            body[0]["recorded_at"].replace("Z", "+00:00")
        )
        assert datetime.now(UTC) - recorded_at < timedelta(minutes=1)

    async def test_location_requires_collector_role_and_valid_coordinates(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        investor = await _make_user(
            db_session, "inv-location-denied@x.com", UserRole.INVESTOR
        )
        headers = await _login(client, investor)

        forbidden = await client.post(
            "/api/v1/collectors/me/location",
            headers=headers,
            json={"latitude": 11.0, "longitude": 77.0},
        )
        assert forbidden.status_code == 403

        collector = await _make_user(
            db_session, "col-location-invalid@x.com", UserRole.COLLECTOR
        )
        collector_headers = await _login(client, collector)
        invalid = await client.post(
            "/api/v1/collectors/me/location",
            headers=collector_headers,
            json={"latitude": 91.0, "longitude": 77.0},
        )
        assert invalid.status_code == 422

    async def test_deactivated_collector_location_is_hidden(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        investor = await _make_user(
            db_session, "inv-location-hidden@x.com", UserRole.INVESTOR
        )
        collector = await _make_user(
            db_session, "col-location-hidden@x.com", UserRole.COLLECTOR
        )
        collector_headers = await _login(client, collector)
        assert (
            await client.post(
                "/api/v1/collectors/me/location",
                headers=collector_headers,
                json={"latitude": 11.0, "longitude": 77.0},
            )
        ).status_code == 204
        collector.is_active = False
        await db_session.flush()

        investor_headers = await _login(client, investor)
        response = await client.get(
            "/api/v1/collectors/locations", headers=investor_headers
        )
        assert response.status_code == 200
        assert response.json() == []
