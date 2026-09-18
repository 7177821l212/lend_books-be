"""Integration tests for BALANCE loans — the notebook model.

A balance loan keeps no schedule. The collector records what was actually
handed over on the day it was handed over, and the loan tracks one number:
repayable minus collected. There are no installments, no allocation, no due
dates and nothing to reschedule.
"""

from datetime import date, timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants.enums import UserRole
from src.data.models.postgres.customer import Customer
from src.data.models.postgres.user import User
from src.utils.security import hash_password


async def _make_user(
    db: AsyncSession, email: str, role: UserRole = UserRole.INVESTOR
) -> User:
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


async def _make_customer(db: AsyncSession, phone: str) -> Customer:
    customer = Customer(
        name=f"Cust {phone[-3:]}", phone=phone, location="X",
        risk_level="medium", is_blacklisted=False,
    )
    db.add(customer)
    await db.flush()
    await db.refresh(customer)
    return customer


async def _login(client: AsyncClient, user: User) -> dict[str, str]:
    res = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "pw12345"}
    )
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


async def _setup(
    client: AsyncClient, db: AsyncSession, suffix: str, *, principal: int = 20_000
) -> tuple[dict[str, str], dict[str, str], dict[str, Any]]:
    """Investor + collector + customer + one ₹20,000 @10% balance loan."""
    investor = await _make_user(db, f"binv{suffix}@x.com")
    collector = await _make_user(db, f"bcol{suffix}@x.com", UserRole.COLLECTOR)
    customer = await _make_customer(db, f"8{suffix.rjust(9, '0')}")
    inv_headers = await _login(client, investor)
    col_headers = await _login(client, collector)
    res = await client.post(
        "/api/v1/loans",
        headers=inv_headers,
        json={
            "customer_id": customer.id,
            "collector_id": collector.id,
            "principal": principal,
            "interest_type": "pct",
            "interest_value": 10,
            "lending_model": "model_b",
            "collection_mode": "balance",
            "start_date": date.today().isoformat(),
        },
    )
    assert res.status_code == 201, res.text
    return inv_headers, col_headers, res.json()


async def _collect(
    client: AsyncClient,
    headers: dict[str, str],
    loan_id: str,
    amount: int,
    on: date | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {"loan_id": loan_id, "amount": amount, "mode": "CASH"}
    if on is not None:
        body["collected_on"] = on.isoformat()
    res = await client.post("/api/v1/payments/collect", headers=headers, json=body)
    assert res.status_code in (200, 201), res.text
    return res.json()


class TestRegistration:
    async def test_a_balance_loan_is_only_money_terms(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """₹20,000 at 10% = ₹22,000 to collect. No schedule is generated."""
        inv_headers, _, loan = await _setup(client, db_session, "1")
        assert loan["principal"] == 20_000
        assert loan["profit"] == 2_000
        assert loan["repayable"] == 22_000
        assert loan["collection_mode"] == "balance"
        assert loan["outstanding"] == 22_000
        assert loan["repaid"] == 0
        assert loan["installments"] == [], "a balance loan has no schedule"
        assert loan["total_installments"] is None
        assert loan["installment_amount"] is None

    async def test_installment_count_is_rejected_for_a_balance_loan(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        investor = await _make_user(db_session, "binv2@x.com")
        collector = await _make_user(db_session, "bcol2@x.com", UserRole.COLLECTOR)
        customer = await _make_customer(db_session, "8000000002")
        headers = await _login(client, investor)
        res = await client.post(
            "/api/v1/loans",
            headers=headers,
            json={
                "customer_id": customer.id,
                "collector_id": collector.id,
                "principal": 20_000,
                "interest_type": "pct",
                "interest_value": 10,
                "lending_model": "model_b",
                "collection_mode": "balance",
                "total_installments": 10,
                "start_date": date.today().isoformat(),
            },
        )
        assert res.status_code == 422
        assert "keep no schedule" in res.text


class TestFlexibleCollection:
    async def test_the_worked_example_from_the_requirement(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """₹1,100 / ₹500 / ₹2,000 / ₹5,000 on four different days."""
        inv_headers, col_headers, loan = await _setup(client, db_session, "3")
        today = date.today()
        schedule = [
            (today - timedelta(days=14), 1_100, 1_100, 20_900),
            (today - timedelta(days=10), 500, 1_600, 20_400),
            (today - timedelta(days=7), 2_000, 3_600, 18_400),
            (today - timedelta(days=3), 5_000, 8_600, 13_400),
        ]
        for on, amount, expected_collected, expected_remaining in schedule:
            payment = await _collect(client, col_headers, loan["id"], amount, on=on)
            assert payment["amount"] == amount
            assert payment["collected_at"][:10] == on.isoformat(), "keeps its real date"
            assert payment["allocations"] == [], "nothing to allocate against"

            detail = (
                await client.get(f"/api/v1/loans/{loan['id']}", headers=inv_headers)
            ).json()
            assert detail["repaid"] == expected_collected
            assert detail["outstanding"] == expected_remaining
            assert detail["repaid"] + detail["outstanding"] == 22_000

    async def test_collection_history_is_the_whole_record(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        inv_headers, col_headers, loan = await _setup(client, db_session, "4")
        today = date.today()
        for days_ago, amount in ((5, 1_100), (3, 500), (1, 2_000)):
            await _collect(
                client, col_headers, loan["id"], amount,
                on=today - timedelta(days=days_ago),
            )
        history = (
            await client.get(
                f"/api/v1/payments/history?loan_id={loan['id']}", headers=inv_headers
            )
        ).json()["items"]
        assert [p["amount"] for p in history] == [2_000, 500, 1_100], "newest first"
        assert [p["collected_at"][:10] for p in history] == [
            (today - timedelta(days=1)).isoformat(),
            (today - timedelta(days=3)).isoformat(),
            (today - timedelta(days=5)).isoformat(),
        ]

    async def test_a_future_collection_date_is_refused(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        _, col_headers, loan = await _setup(client, db_session, "5")
        res = await client.post(
            "/api/v1/payments/collect",
            headers=col_headers,
            json={
                "loan_id": loan["id"],
                "amount": 1_000,
                "mode": "CASH",
                "collected_on": (date.today() + timedelta(days=1)).isoformat(),
            },
        )
        assert res.status_code == 422
        assert "future" in res.text

    async def test_cannot_collect_more_than_remains(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        _, col_headers, loan = await _setup(client, db_session, "6")
        await _collect(client, col_headers, loan["id"], 20_000)
        res = await client.post(
            "/api/v1/payments/collect",
            headers=col_headers,
            json={"loan_id": loan["id"], "amount": 2_001, "mode": "CASH"},
        )
        assert res.status_code == 409
        assert "2,000" in res.text, "tells the collector what is actually left"


class TestClosure:
    async def test_the_loan_closes_when_the_total_is_reached(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        inv_headers, col_headers, loan = await _setup(client, db_session, "7")
        await _collect(client, col_headers, loan["id"], 15_000)
        detail = (
            await client.get(f"/api/v1/loans/{loan['id']}", headers=inv_headers)
        ).json()
        assert detail["status"] == "active"

        await _collect(client, col_headers, loan["id"], 7_000)
        detail = (
            await client.get(f"/api/v1/loans/{loan['id']}", headers=inv_headers)
        ).json()
        assert detail["repaid"] == 22_000
        assert detail["outstanding"] == 0
        assert detail["status"] == "closed"

    async def test_a_closed_loan_takes_no_more_money(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        _, col_headers, loan = await _setup(client, db_session, "8")
        await _collect(client, col_headers, loan["id"], 22_000)
        res = await client.post(
            "/api/v1/payments/collect",
            headers=col_headers,
            json={"loan_id": loan["id"], "amount": 100, "mode": "CASH"},
        )
        assert res.status_code == 409


class TestWorklistAndScheduleOperations:
    async def test_a_balance_loan_stays_on_the_round_until_it_is_cleared(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """No due dates, so it simply appears every day while it is active."""
        _, col_headers, loan = await _setup(client, db_session, "9")
        my_day = (
            await client.get("/api/v1/payments/my-day", headers=col_headers)
        ).json()
        pickup = next(p for p in my_day["pickups"] if p["loan_id"] == loan["id"])
        assert pickup["collection_mode"] == "balance"
        assert pickup["due_amount"] == 22_000, "shows what is LEFT, not an amount due"
        assert pickup["due_date"] is None and pickup["schedule_id"] is None
        assert pickup["is_overdue"] is False
        assert my_day["target_total"] == 0, "a balance loan owes nothing *today*"

        await _collect(client, col_headers, loan["id"], 8_600)
        my_day = (
            await client.get("/api/v1/payments/my-day", headers=col_headers)
        ).json()
        pickup = next(p for p in my_day["pickups"] if p["loan_id"] == loan["id"])
        assert pickup["due_amount"] == 13_400

    async def test_a_cleared_balance_loan_leaves_the_round(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        _, col_headers, loan = await _setup(client, db_session, "10")
        await _collect(client, col_headers, loan["id"], 22_000)
        my_day = (
            await client.get("/api/v1/payments/my-day", headers=col_headers)
        ).json()
        assert all(p["loan_id"] != loan["id"] for p in my_day["pickups"])

    async def test_schedule_only_operations_are_refused(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        inv_headers, col_headers, loan = await _setup(client, db_session, "11")
        missed = await client.post(
            "/api/v1/payments/missed",
            headers=col_headers,
            json={"loan_id": loan["id"], "schedule_id": "any", "reason": "shut"},
        )
        assert missed.status_code == 409
        assert "no schedule" in missed.text

        reschedule = await client.post(
            f"/api/v1/loans/{loan['id']}/reschedule",
            headers=inv_headers,
            json={"reason": "Customer request", "mode": "same_end_date"},
        )
        assert reschedule.status_code == 409
        assert "no schedule" in reschedule.text
