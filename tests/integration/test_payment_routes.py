"""Integration tests for /payments/* endpoints."""

from datetime import date, timedelta
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


async def _make_customer(db: AsyncSession, phone: str) -> Customer:
    c = Customer(
        name=f"Cust {phone[-3:]}",
        phone=phone,
        location="X",
        risk_level="medium",
        is_blacklisted=False,
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


async def _create_loan(
    client: AsyncClient,
    inv_headers: dict[str, str],
    customer_id: str,
    collector_id: str,
    **overrides: Any,
) -> dict[str, Any]:
    res = await client.post(
        "/api/v1/loans",
        headers=inv_headers,
        json=_loan_payload(customer_id, collector_id, **overrides),
    )
    assert res.status_code == 201
    return res.json()


@pytest.mark.integration
class TestCollect:
    async def test_collector_can_pay_full_installment(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        investor = await _make_user(db_session, "inv-pay1@x.com")
        collector = await _make_user(db_session, "col-pay1@x.com", role=UserRole.COLLECTOR)
        customer = await _make_customer(db_session, "9999901001")
        inv_headers = await _login(client, investor)
        loan = await _create_loan(client, inv_headers, customer.id, collector.id)

        col_headers = await _login(client, collector)
        first_inst = loan["installments"][0]
        res = await client.post(
            "/api/v1/payments/collect",
            headers=col_headers,
            json={
                "loan_id": loan["id"],
                "amount": first_inst["due_amount"],
                "mode": "CASH",
                "schedule_id": first_inst["id"],
            },
        )
        assert res.status_code == 201
        body = res.json()
        assert body["is_missed"] is False
        assert body["amount"] == first_inst["due_amount"]
        assert body["schedule_id"] == first_inst["id"]

        # Loan should show the payment via /loans/{id}
        loan_after = await client.get(f"/api/v1/loans/{loan['id']}", headers=col_headers)
        body_after = loan_after.json()
        assert body_after["paid_count"] == 1
        assert body_after["outstanding"] == loan["repayable"] - first_inst["due_amount"]

    async def test_partial_payment_marks_partial(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        investor = await _make_user(db_session, "inv-pay2@x.com")
        collector = await _make_user(db_session, "col-pay2@x.com", role=UserRole.COLLECTOR)
        customer = await _make_customer(db_session, "9999901002")
        inv_headers = await _login(client, investor)
        loan = await _create_loan(client, inv_headers, customer.id, collector.id)

        col_headers = await _login(client, collector)
        first = loan["installments"][0]
        partial = first["due_amount"] // 2
        await client.post(
            "/api/v1/payments/collect",
            headers=col_headers,
            json={"loan_id": loan["id"], "amount": partial, "mode": "UPI", "schedule_id": first["id"]},
        )
        detail = await client.get(f"/api/v1/loans/{loan['id']}", headers=col_headers)
        rows = detail.json()["installments"]
        assert rows[0]["status"] == "partial"
        assert rows[0]["paid_amount"] == partial

    async def test_collector_cannot_collect_other_collector_loan(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        investor = await _make_user(db_session, "inv-pay3@x.com")
        col_a = await _make_user(db_session, "col-pay3a@x.com", role=UserRole.COLLECTOR)
        col_b = await _make_user(db_session, "col-pay3b@x.com", role=UserRole.COLLECTOR)
        customer = await _make_customer(db_session, "9999901003")
        inv_headers = await _login(client, investor)
        loan = await _create_loan(client, inv_headers, customer.id, col_a.id)

        b_headers = await _login(client, col_b)
        res = await client.post(
            "/api/v1/payments/collect",
            headers=b_headers,
            json={"loan_id": loan["id"], "amount": 1000, "mode": "CASH"},
        )
        assert res.status_code == 403

    async def test_fully_paying_loan_closes_it(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        investor = await _make_user(db_session, "inv-pay4@x.com")
        collector = await _make_user(db_session, "col-pay4@x.com", role=UserRole.COLLECTOR)
        customer = await _make_customer(db_session, "9999901004")
        inv_headers = await _login(client, investor)
        # 2-installment loan for a quick close
        loan = await _create_loan(
            client, inv_headers, customer.id, collector.id, total_installments=2
        )

        col_headers = await _login(client, collector)
        for inst in loan["installments"]:
            await client.post(
                "/api/v1/payments/collect",
                headers=col_headers,
                json={
                    "loan_id": loan["id"],
                    "amount": inst["due_amount"],
                    "mode": "CASH",
                    "schedule_id": inst["id"],
                },
            )

        # Use investor token to verify status — collector lost view rights since loan is closed
        detail = await client.get(f"/api/v1/loans/{loan['id']}", headers=inv_headers)
        body = detail.json()
        assert body["status"] == "closed"
        assert body["outstanding"] == 0


@pytest.mark.integration
class TestMissed:
    async def test_mark_missed_creates_record_and_status(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        investor = await _make_user(db_session, "inv-mis1@x.com")
        collector = await _make_user(db_session, "col-mis1@x.com", role=UserRole.COLLECTOR)
        customer = await _make_customer(db_session, "9999901010")
        inv_headers = await _login(client, investor)
        loan = await _create_loan(client, inv_headers, customer.id, collector.id)
        col_headers = await _login(client, collector)

        first = loan["installments"][0]
        res = await client.post(
            "/api/v1/payments/missed",
            headers=col_headers,
            json={
                "loan_id": loan["id"],
                "schedule_id": first["id"],
                "reason": "Customer unavailable",
            },
        )
        assert res.status_code == 201
        body = res.json()
        assert body["is_missed"] is True
        assert body["missed_reason"] == "Customer unavailable"

        detail = await client.get(f"/api/v1/loans/{loan['id']}", headers=col_headers)
        rows = detail.json()["installments"]
        assert rows[0]["status"] == "missed"


@pytest.mark.integration
class TestMyDay:
    async def test_my_day_lists_pickups_for_today_and_overdue(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        investor = await _make_user(db_session, "inv-my1@x.com")
        collector = await _make_user(db_session, "col-my1@x.com", role=UserRole.COLLECTOR)
        customer = await _make_customer(db_session, "9999901020")
        inv_headers = await _login(client, investor)
        # Loan that started 3 days ago — first 3 installments are now due/overdue
        loan = await _create_loan(
            client,
            inv_headers,
            customer.id,
            collector.id,
            start_date=(date.today() - timedelta(days=2)).isoformat(),
            total_installments=10,
        )

        col_headers = await _login(client, collector)
        res = await client.get("/api/v1/payments/my-day", headers=col_headers)
        assert res.status_code == 200
        body = res.json()
        assert body["pickup_count"] >= 3
        assert body["target_total"] > 0
        first_pickup = body["pickups"][0]
        assert first_pickup["customer_name"] == customer.name
        assert first_pickup["loan_id"] == loan["id"]
        assert first_pickup["is_overdue"] is True

    async def test_investor_cannot_call_my_day(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        investor = await _make_user(db_session, "inv-my2@x.com")
        headers = await _login(client, investor)
        res = await client.get("/api/v1/payments/my-day", headers=headers)
        assert res.status_code == 403


@pytest.mark.integration
class TestHistory:
    async def test_collector_history_only_returns_own_payments(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        investor = await _make_user(db_session, "inv-hi@x.com")
        col_a = await _make_user(db_session, "col-hi-a@x.com", role=UserRole.COLLECTOR)
        col_b = await _make_user(db_session, "col-hi-b@x.com", role=UserRole.COLLECTOR)
        cust_a = await _make_customer(db_session, "9999901030")
        cust_b = await _make_customer(db_session, "9999901031")
        inv_headers = await _login(client, investor)
        loan_a = await _create_loan(client, inv_headers, cust_a.id, col_a.id)
        loan_b = await _create_loan(client, inv_headers, cust_b.id, col_b.id)

        a_headers = await _login(client, col_a)
        await client.post(
            "/api/v1/payments/collect",
            headers=a_headers,
            json={
                "loan_id": loan_a["id"],
                "amount": loan_a["installments"][0]["due_amount"],
                "mode": "CASH",
                "schedule_id": loan_a["installments"][0]["id"],
            },
        )
        b_headers = await _login(client, col_b)
        await client.post(
            "/api/v1/payments/collect",
            headers=b_headers,
            json={
                "loan_id": loan_b["id"],
                "amount": loan_b["installments"][0]["due_amount"],
                "mode": "CASH",
                "schedule_id": loan_b["installments"][0]["id"],
            },
        )

        res_a = await client.get("/api/v1/payments/history", headers=a_headers)
        items = res_a.json()["items"]
        assert len(items) == 1
        assert items[0]["loan_id"] == loan_a["id"]
