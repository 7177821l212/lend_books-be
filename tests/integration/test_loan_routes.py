"""Integration tests for /loans/* endpoints."""

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


async def _make_customer(db: AsyncSession, phone: str = "9999900100") -> Customer:
    c = Customer(name="Test Cust", phone=phone, location="X", risk_level="medium", is_blacklisted=False)
    db.add(c)
    await db.flush()
    await db.refresh(c)
    return c


async def _login(client: AsyncClient, user: User, password: str = "pw12345") -> dict[str, str]:
    res = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": password}
    )
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _payload(customer_id: str, collector_id: str, **overrides: Any) -> dict[str, Any]:
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
class TestCreateLoan:
    async def test_model_a_creates_with_schedule_and_correct_math(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        investor = await _make_user(db_session, "inv-l1@x.com")
        collector = await _make_user(db_session, "col-l1@x.com", role=UserRole.COLLECTOR)
        customer = await _make_customer(db_session)
        headers = await _login(client, investor)

        res = await client.post(
            "/api/v1/loans",
            headers=headers,
            json=_payload(customer.id, collector.id, principal=10000, interest_value=10),
        )
        assert res.status_code == 201
        body = res.json()
        assert body["disbursed"] == 9000
        assert body["repayable"] == 10000
        assert body["profit"] == 1000
        assert body["lending_model"] == "model_a"
        assert len(body["installments"]) == 10
        assert sum(i["due_amount"] for i in body["installments"]) == 10000
        assert body["installments"][0]["due_amount"] == 1000

    async def test_model_b_creates_with_correct_math(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        investor = await _make_user(db_session, "inv-l2@x.com")
        collector = await _make_user(db_session, "col-l2@x.com", role=UserRole.COLLECTOR)
        customer = await _make_customer(db_session, phone="9999900101")
        headers = await _login(client, investor)

        res = await client.post(
            "/api/v1/loans",
            headers=headers,
            json=_payload(
                customer.id,
                collector.id,
                principal=20000,
                interest_value=12,
                lending_model="model_b",
                repayment_frequency="weekly",
                total_installments=8,
            ),
        )
        assert res.status_code == 201
        body = res.json()
        assert body["disbursed"] == 20000
        assert body["repayable"] == 22400
        assert body["profit"] == 2400
        assert len(body["installments"]) == 8
        assert sum(i["due_amount"] for i in body["installments"]) == 22400

    async def test_fixed_interest(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        investor = await _make_user(db_session, "inv-l3@x.com")
        collector = await _make_user(db_session, "col-l3@x.com", role=UserRole.COLLECTOR)
        customer = await _make_customer(db_session, phone="9999900102")
        headers = await _login(client, investor)

        res = await client.post(
            "/api/v1/loans",
            headers=headers,
            json=_payload(
                customer.id,
                collector.id,
                principal=15000,
                interest_type="fixed",
                interest_value=1500,
                lending_model="model_a",
                total_installments=30,
            ),
        )
        assert res.status_code == 201
        body = res.json()
        assert body["interest_type"] == "fixed"
        assert body["disbursed"] == 13500
        assert body["repayable"] == 15000

    async def test_collector_cannot_create(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        col = await _make_user(db_session, "col-c@x.com", role=UserRole.COLLECTOR)
        other_col = await _make_user(db_session, "col-d@x.com", role=UserRole.COLLECTOR)
        customer = await _make_customer(db_session, phone="9999900103")
        headers = await _login(client, col)

        res = await client.post(
            "/api/v1/loans", headers=headers, json=_payload(customer.id, other_col.id)
        )
        assert res.status_code == 403

    async def test_blacklisted_customer_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        investor = await _make_user(db_session, "inv-bl@x.com")
        collector = await _make_user(db_session, "col-bl@x.com", role=UserRole.COLLECTOR)
        customer = await _make_customer(db_session, phone="9999900104")
        customer.is_blacklisted = True
        await db_session.flush()
        headers = await _login(client, investor)

        res = await client.post(
            "/api/v1/loans", headers=headers, json=_payload(customer.id, collector.id)
        )
        assert res.status_code == 409

    async def test_soft_deleted_customer_cannot_receive_a_new_loan(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        investor = await _make_user(db_session, "inv-deleted@x.com")
        collector = await _make_user(
            db_session, "col-deleted@x.com", role=UserRole.COLLECTOR
        )
        customer = await _make_customer(db_session, phone="9999900106")
        customer.is_deleted = True
        await db_session.flush()
        headers = await _login(client, investor)

        res = await client.post(
            "/api/v1/loans", headers=headers, json=_payload(customer.id, collector.id)
        )
        assert res.status_code == 404

    async def test_pct_above_100_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        investor = await _make_user(db_session, "inv-pct@x.com")
        collector = await _make_user(db_session, "col-pct@x.com", role=UserRole.COLLECTOR)
        customer = await _make_customer(db_session, phone="9999900105")
        headers = await _login(client, investor)

        res = await client.post(
            "/api/v1/loans",
            headers=headers,
            json=_payload(customer.id, collector.id, interest_value=150),
        )
        assert res.status_code == 422


@pytest.mark.integration
class TestLoanList:
    async def test_collector_sees_only_own_loans(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        investor = await _make_user(db_session, "inv-list@x.com")
        col1 = await _make_user(db_session, "col-list1@x.com", role=UserRole.COLLECTOR)
        col2 = await _make_user(db_session, "col-list2@x.com", role=UserRole.COLLECTOR)
        customer = await _make_customer(db_session, phone="9999900110")

        inv_headers = await _login(client, investor)
        # Create two loans, different collectors
        await client.post(
            "/api/v1/loans",
            headers=inv_headers,
            json=_payload(customer.id, col1.id),
        )
        # Need another customer for second loan
        customer2 = await _make_customer(db_session, phone="9999900111")
        await client.post(
            "/api/v1/loans",
            headers=inv_headers,
            json=_payload(customer2.id, col2.id),
        )

        # Investor sees both
        res = await client.get("/api/v1/loans", headers=inv_headers)
        assert res.json()["total"] == 2

        # col1 sees only their loan
        col1_headers = await _login(client, col1)
        res = await client.get("/api/v1/loans", headers=col1_headers)
        assert res.json()["total"] == 1


@pytest.mark.integration
class TestCloseLoan:
    async def test_investor_can_close(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        investor = await _make_user(db_session, "inv-cl@x.com")
        collector = await _make_user(db_session, "col-cl@x.com", role=UserRole.COLLECTOR)
        customer = await _make_customer(db_session, phone="9999900120")
        headers = await _login(client, investor)

        created = await client.post(
            "/api/v1/loans", headers=headers, json=_payload(customer.id, collector.id)
        )
        loan_id = created.json()["id"]

        res = await client.post(
            f"/api/v1/loans/{loan_id}/close",
            headers=headers,
            json={"reason": "Customer paid in cash"},
        )
        assert res.status_code == 200
        assert res.json()["status"] == "closed"

    async def test_collector_cannot_close(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        investor = await _make_user(db_session, "inv-cl2@x.com")
        collector = await _make_user(db_session, "col-cl2@x.com", role=UserRole.COLLECTOR)
        customer = await _make_customer(db_session, phone="9999900121")
        inv_headers = await _login(client, investor)
        created = await client.post(
            "/api/v1/loans", headers=inv_headers, json=_payload(customer.id, collector.id)
        )
        loan_id = created.json()["id"]

        col_headers = await _login(client, collector)
        res = await client.post(f"/api/v1/loans/{loan_id}/close", headers=col_headers)
        assert res.status_code == 403


@pytest.mark.integration
class TestAssignCollector:
    async def test_reassign(self, client: AsyncClient, db_session: AsyncSession) -> None:
        investor = await _make_user(db_session, "inv-as@x.com")
        c1 = await _make_user(db_session, "col-as1@x.com", role=UserRole.COLLECTOR)
        c2 = await _make_user(db_session, "col-as2@x.com", role=UserRole.COLLECTOR)
        customer = await _make_customer(db_session, phone="9999900130")
        headers = await _login(client, investor)

        created = await client.post(
            "/api/v1/loans", headers=headers, json=_payload(customer.id, c1.id)
        )
        loan_id = created.json()["id"]

        res = await client.post(
            f"/api/v1/loans/{loan_id}/assign",
            headers=headers,
            json={"collector_id": c2.id},
        )
        assert res.status_code == 200
        assert res.json()["collector_id"] == c2.id


@pytest.mark.integration
class TestCollectorPicker:
    async def test_inactive_collectors_not_listed(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        investor = await _make_user(db_session, "inv-cp@x.com")
        active = await _make_user(
            db_session, "col-cp1@x.com", role=UserRole.COLLECTOR
        )
        inactive = await _make_user(
            db_session, "col-cp2@x.com", role=UserRole.COLLECTOR
        )
        inactive.is_active = False
        await db_session.flush()

        headers = await _login(client, investor)
        res = await client.get("/api/v1/collectors", headers=headers)
        assert res.status_code == 200
        ids = {c["id"] for c in res.json()}
        assert active.id in ids
        assert inactive.id not in ids


@pytest.mark.integration
class TestInstallmentAmountContract:
    async def test_uneven_repayable_exposes_distinct_base_and_max(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Repayable that doesn't divide evenly must surface both base and max."""
        investor = await _make_user(db_session, "inv-ia@x.com")
        collector = await _make_user(db_session, "col-ia@x.com", role=UserRole.COLLECTOR)
        customer = await _make_customer(db_session, phone="9999900200")
        headers = await _login(client, investor)
        # principal 10000 + 10% Model B → repayable 11000. 11000 / 7 = 1571 r=3
        res = await client.post(
            "/api/v1/loans",
            headers=headers,
            json=_payload(
                customer.id,
                collector.id,
                principal=10000,
                interest_value=10,
                lending_model="model_b",
                total_installments=7,
            ),
        )
        assert res.status_code == 201
        body = res.json()
        assert body["installment_amount"] == 1571
        assert body["installment_amount_max"] == 1572
        assert sum(i["due_amount"] for i in body["installments"]) == 11000

    async def test_even_repayable_base_equals_max(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        investor = await _make_user(db_session, "inv-ie@x.com")
        collector = await _make_user(db_session, "col-ie@x.com", role=UserRole.COLLECTOR)
        customer = await _make_customer(db_session, phone="9999900201")
        headers = await _login(client, investor)
        res = await client.post(
            "/api/v1/loans",
            headers=headers,
            json=_payload(customer.id, collector.id, principal=10000, interest_value=10),
        )
        body = res.json()
        assert body["installment_amount"] == 1000
        assert body["installment_amount_max"] == 1000


@pytest.mark.integration
class TestCustomerOutstanding:
    async def test_customer_list_includes_outstanding(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        investor = await _make_user(db_session, "inv-out@x.com")
        collector = await _make_user(db_session, "col-out@x.com", role=UserRole.COLLECTOR)
        customer = await _make_customer(db_session, phone="9999900140")
        headers = await _login(client, investor)

        await client.post(
            "/api/v1/loans",
            headers=headers,
            json=_payload(customer.id, collector.id, principal=10000, lending_model="model_b"),
        )

        res = await client.get("/api/v1/customers", headers=headers)
        body = res.json()
        cust = next(c for c in body["items"] if c["id"] == customer.id)
        assert cust["active_loan_count"] == 1
        assert cust["total_outstanding"] == 11000  # principal + 10% interest, nothing paid yet
