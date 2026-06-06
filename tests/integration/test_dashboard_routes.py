"""Integration tests for /dashboard and /reports."""

from datetime import date
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants.enums import UserRole
from src.data.models.postgres.customer import Customer
from src.data.models.postgres.user import User
from src.utils.security import hash_password


async def _make_user(
    db: AsyncSession,
    email: str,
    role: UserRole = UserRole.INVESTOR,
    password: str = "pw12345",
) -> User:
    u = User(
        email=email,
        name=email.split("@")[0],
        hashed_password=hash_password(password),
        role=role.value,
        is_active=True,
    )
    db.add(u)
    await db.flush()
    await db.refresh(u)
    return u


async def _make_customer(
    db: AsyncSession, phone: str, blacklisted: bool = False
) -> Customer:
    c = Customer(
        name=f"Cust {phone[-3:]}",
        phone=phone,
        location="X",
        risk_level="medium",
        is_blacklisted=blacklisted,
        blacklist_reason="test" if blacklisted else None,
    )
    db.add(c)
    await db.flush()
    await db.refresh(c)
    return c


async def _login(client: AsyncClient, user: User, password: str = "pw12345") -> dict[str, str]:
    res = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": password}
    )
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _loan_payload(customer_id: str, collector_id: str, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "customer_id": customer_id,
        "collector_id": collector_id,
        "principal": 10000,
        "interest_type": "pct",
        "interest_value": 10,
        "lending_model": "model_a",
        "repayment_frequency": "daily",
        "total_installments": 10,
        "start_date": date.today().isoformat(),
    }
    base.update(overrides)
    return base


@pytest.mark.integration
class TestDashboard:
    async def test_dashboard_returns_zero_kpis_on_empty(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        investor = await _make_user(db_session, "inv-d1@x.com")
        headers = await _login(client, investor)
        res = await client.get("/api/v1/dashboard", headers=headers)
        assert res.status_code == 200
        body = res.json()
        assert body["kpis"]["capital_disbursed"] == 0
        assert body["kpis"]["active_loans"] == 0
        assert len(body["trend_30d"]) == 30

    async def test_dashboard_reflects_real_loans_and_payments(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        investor = await _make_user(db_session, "inv-d2@x.com")
        collector = await _make_user(db_session, "col-d2@x.com", role=UserRole.COLLECTOR)
        customer = await _make_customer(db_session, "9999902001")
        inv_headers = await _login(client, investor)

        loan_res = await client.post(
            "/api/v1/loans",
            headers=inv_headers,
            json=_loan_payload(customer.id, collector.id),
        )
        loan = loan_res.json()

        col_headers = await _login(client, collector)
        first = loan["installments"][0]
        await client.post(
            "/api/v1/payments/collect",
            headers=col_headers,
            json={
                "loan_id": loan["id"],
                "amount": first["due_amount"],
                "mode": "CASH",
                "schedule_id": first["id"],
            },
        )

        res = await client.get("/api/v1/dashboard", headers=inv_headers)
        body = res.json()
        assert body["kpis"]["capital_disbursed"] == loan["disbursed"]
        assert body["kpis"]["collected_lifetime"] == first["due_amount"]
        assert body["kpis"]["collected_today"] == first["due_amount"]
        assert body["kpis"]["active_loans"] == 1
        assert body["kpis"]["active_customers"] == 1

    async def test_collector_cannot_call_dashboard(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        col = await _make_user(db_session, "col-d3@x.com", role=UserRole.COLLECTOR)
        headers = await _login(client, col)
        res = await client.get("/api/v1/dashboard", headers=headers)
        assert res.status_code == 403


@pytest.mark.integration
class TestReports:
    async def test_reports_lists_blacklisted_customers(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        investor = await _make_user(db_session, "inv-r1@x.com")
        await _make_customer(db_session, "9999902010", blacklisted=True)
        await _make_customer(db_session, "9999902011")
        headers = await _login(client, investor)
        res = await client.get("/api/v1/reports", headers=headers)
        assert res.status_code == 200
        body = res.json()
        assert len(body["blacklisted"]) == 1
        assert body["blacklisted"][0]["reason"] == "test"

    async def test_collector_cannot_call_reports(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        col = await _make_user(db_session, "col-r2@x.com", role=UserRole.COLLECTOR)
        headers = await _login(client, col)
        res = await client.get("/api/v1/reports", headers=headers)
        assert res.status_code == 403
