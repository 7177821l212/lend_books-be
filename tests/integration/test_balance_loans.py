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
    async def test_a_balance_loan_shows_what_is_left_until_it_is_collected(
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

        # Once collected, the visit is done and the loan leaves today's round.
        await _collect(client, col_headers, loan["id"], 8_600)
        my_day = (
            await client.get("/api/v1/payments/my-day", headers=col_headers)
        ).json()
        assert all(p["loan_id"] != loan["id"] for p in my_day["pickups"])

    async def test_a_cleared_balance_loan_leaves_the_round(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        _, col_headers, loan = await _setup(client, db_session, "10")
        await _collect(client, col_headers, loan["id"], 22_000)
        my_day = (
            await client.get("/api/v1/payments/my-day", headers=col_headers)
        ).json()
        assert all(p["loan_id"] != loan["id"] for p in my_day["pickups"])

    async def test_rescheduling_is_refused(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """There is no schedule to revise — the customer pays what they can."""
        inv_headers, _, loan = await _setup(client, db_session, "11")
        reschedule = await client.post(
            f"/api/v1/loans/{loan['id']}/reschedule",
            headers=inv_headers,
            json={"reason": "Customer request", "mode": "same_end_date"},
        )
        assert reschedule.status_code == 409
        assert "no schedule" in reschedule.text


class TestExpectedPaceAndMissedVisits:
    """The installment count is a GUIDE on a balance loan, never a rule."""

    async def _loan_with_installments(
        self, client: AsyncClient, db: AsyncSession, suffix: str, installments: int
    ) -> tuple[dict[str, str], dict[str, str], dict[str, Any]]:
        investor = await _make_user(db, f"pinv{suffix}@x.com")
        collector = await _make_user(db, f"pcol{suffix}@x.com", UserRole.COLLECTOR)
        customer = await _make_customer(db, f"7{suffix.rjust(9, '0')}")
        inv = await _login(client, investor)
        col = await _login(client, collector)
        res = await client.post(
            "/api/v1/loans",
            headers=inv,
            json={
                "customer_id": customer.id,
                "collector_id": collector.id,
                "principal": 20_000,
                "interest_type": "pct",
                "interest_value": 10,
                "lending_model": "model_b",
                "collection_mode": "balance",
                "total_installments": installments,
                "start_date": date.today().isoformat(),
            },
        )
        assert res.status_code == 201, res.text
        return inv, col, res.json()

    async def test_the_per_visit_amount_is_derived_but_not_enforced(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        inv, col, loan = await self._loan_with_installments(client, db_session, "1", 20)
        assert loan["repayable"] == 22_000
        assert loan["total_installments"] == 20
        assert loan["installment_amount"] == 1_100, "₹22,000 over 20 visits"
        assert loan["installments"] == [], "still no schedule rows"

        # The customer pays nothing like ₹1,100 and every payment is accepted.
        for amount in (1_000, 500, 700):
            await _collect(client, col, loan["id"], amount)
        detail = (
            await client.get(f"/api/v1/loans/{loan['id']}", headers=inv)
        ).json()
        assert detail["repaid"] == 2_200
        assert detail["outstanding"] == 19_800
        assert detail["installment_amount"] == 1_100, "the guide does not move"

    async def test_a_day_can_be_marked_missed_with_a_reason(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Day 1 ₹1,000 · day 2 ₹500 · day 3 missed · day 4 ₹700."""
        inv, col, loan = await self._loan_with_installments(client, db_session, "2", 20)
        today = date.today()
        await _collect(client, col, loan["id"], 1_000, on=today - timedelta(days=3))
        await _collect(client, col, loan["id"], 500, on=today - timedelta(days=2))

        missed = await client.post(
            "/api/v1/payments/missed",
            headers=col,
            json={
                "loan_id": loan["id"],
                "missed_on": (today - timedelta(days=1)).isoformat(),
                "reason": "Shop closed",
            },
        )
        assert missed.status_code in (200, 201), missed.text
        assert missed.json()["is_missed"] is True
        assert missed.json()["amount"] == 0

        await _collect(client, col, loan["id"], 700, on=today)

        detail = (await client.get(f"/api/v1/loans/{loan['id']}", headers=inv)).json()
        assert detail["repaid"] == 2_200, "a missed day moves no money"
        assert detail["outstanding"] == 19_800
        assert detail["total_installments"] == 20, "and does not extend anything"

        history = (
            await client.get(
                f"/api/v1/payments/history?loan_id={loan['id']}", headers=inv
            )
        ).json()["items"]
        assert [(p["amount"], p["is_missed"]) for p in history] == [
            (700, False),
            (0, True),
            (500, False),
            (1_000, False),
        ], "the gap is explained, not silent"
        assert history[1]["missed_reason"] == "Shop closed"

    async def test_installments_remain_optional_on_a_balance_loan(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        _, _, loan = await _setup(client, db_session, "30")
        assert loan["total_installments"] is None
        assert loan["installment_amount"] is None


class TestTellingTwoLoansApart:
    """One customer, two live loans — the round must distinguish them."""

    async def test_pickups_carry_loan_number_start_date_and_missed_count(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        investor = await _make_user(db_session, "minv@x.com")
        collector = await _make_user(db_session, "mcol@x.com", UserRole.COLLECTOR)
        customer = await _make_customer(db_session, "7900000001")
        inv = await _login(client, investor)
        col = await _login(client, collector)
        today = date.today()

        async def make(principal: int, start: date) -> dict[str, Any]:
            res = await client.post(
                "/api/v1/loans",
                headers=inv,
                json={
                    "customer_id": customer.id,
                    "collector_id": collector.id,
                    "principal": principal,
                    "interest_type": "pct",
                    "interest_value": 10,
                    "lending_model": "model_b",
                    "collection_mode": "balance",
                    "total_installments": 10,
                    "start_date": start.isoformat(),
                },
            )
            assert res.status_code == 201, res.text
            return res.json()

        first = await make(10_000, today - timedelta(days=30))
        second = await make(20_000, today - timedelta(days=5))

        # Two missed visits on the older loan only.
        for days_ago in (3, 2):
            res = await client.post(
                "/api/v1/payments/missed",
                headers=col,
                json={
                    "loan_id": first["id"],
                    "missed_on": (today - timedelta(days=days_ago)).isoformat(),
                    "reason": "Shop closed",
                },
            )
            assert res.status_code in (200, 201), res.text

        my_day = (await client.get("/api/v1/payments/my-day", headers=col)).json()
        by_loan = {p["loan_id"]: p for p in my_day["pickups"]}

        older = by_loan[first["id"]]
        newer = by_loan[second["id"]]
        assert older["loan_number"] == 1, "the loan given first is Loan 1"
        assert newer["loan_number"] == 2
        assert older["start_date"] == (today - timedelta(days=30)).isoformat()
        assert newer["start_date"] == (today - timedelta(days=5)).isoformat()
        assert older["missed_count"] == 2
        assert newer["missed_count"] == 0

        # The same identity is on the loan itself, not just the round.
        detail = (
            await client.get(f"/api/v1/loans/{first['id']}", headers=inv)
        ).json()
        assert detail["loan_number"] == 1
        assert detail["missed_count"] == 2


class TestBalanceLoansAreVisibleEverywhere:
    """Cash on a balance loan must reach every surface, not just the loan.

    These figures were computed by summing `Installment.paid_amount`. A balance
    loan has no installments, so its collections were invisible and the balance
    was overstated by exactly what had been collected.
    """

    async def test_dashboard_and_customer_totals_match_the_loans(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        inv, col, loan = await _setup(client, db_session, "40")
        await _collect(client, col, loan["id"], 2_200)

        loans = (
            await client.get("/api/v1/loans?status=active&page_size=50", headers=inv)
        ).json()["items"]
        truth = sum(item["outstanding"] for item in loans)
        assert truth == 19_800, "one active balance loan, ₹2,200 collected"

        kpis = (await client.get("/api/v1/dashboard", headers=inv)).json()["kpis"]
        assert kpis["outstanding"] == truth, "dashboard must see balance collections"

        customer = (
            await client.get(
                f"/api/v1/customers/{loan['customer_id']}", headers=inv
            )
        ).json()
        assert customer["total_outstanding"] == truth, "customer detail must too"

        listed = (
            await client.get("/api/v1/customers?page_size=100", headers=inv)
        ).json()["items"]
        row = next(c for c in listed if c["id"] == loan["customer_id"])
        assert row["total_outstanding"] == truth, "and the customer list"


class TestMissedVisitGuards:
    async def test_the_same_day_cannot_be_missed_twice(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A double tap, or a retry on a flaky connection, is one absence."""
        _, col, loan = await _setup(client, db_session, "50")
        body = {"loan_id": loan["id"], "reason": "Shop closed"}
        first = await client.post("/api/v1/payments/missed", headers=col, json=body)
        assert first.status_code in (200, 201), first.text
        second = await client.post("/api/v1/payments/missed", headers=col, json=body)
        assert second.status_code == 409
        assert "already recorded" in second.text

        detail = (
            await client.get(f"/api/v1/loans/{loan['id']}", headers=col)
        ).json()
        assert detail["missed_count"] == 1

    async def test_a_day_that_took_money_cannot_also_be_missed(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        _, col, loan = await _setup(client, db_session, "51")
        await _collect(client, col, loan["id"], 500)
        res = await client.post(
            "/api/v1/payments/missed",
            headers=col,
            json={"loan_id": loan["id"], "reason": "Shop closed"},
        )
        assert res.status_code == 409
        assert "500" in res.text

    async def test_different_days_can_each_be_missed(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        _, col, loan = await _setup(client, db_session, "52")
        today = date.today()
        for days_ago in (2, 1):
            res = await client.post(
                "/api/v1/payments/missed",
                headers=col,
                json={
                    "loan_id": loan["id"],
                    "missed_on": (today - timedelta(days=days_ago)).isoformat(),
                    "reason": "Shop closed",
                },
            )
            assert res.status_code in (200, 201), res.text
        detail = (await client.get(f"/api/v1/loans/{loan['id']}", headers=col)).json()
        assert detail["missed_count"] == 2


class TestLoanNumberIsStable:
    async def test_a_back_dated_loan_does_not_renumber_the_others(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The collector's notebook says "Loan 2" — it must stay that loan."""
        investor = await _make_user(db_session, "sinv@x.com")
        collector = await _make_user(db_session, "scol@x.com", UserRole.COLLECTOR)
        customer = await _make_customer(db_session, "6900000001")
        inv = await _login(client, investor)
        today = date.today()

        async def make(start: date) -> dict[str, Any]:
            res = await client.post(
                "/api/v1/loans",
                headers=inv,
                json={
                    "customer_id": customer.id,
                    "collector_id": collector.id,
                    "principal": 10_000,
                    "interest_type": "pct",
                    "interest_value": 10,
                    "lending_model": "model_b",
                    "collection_mode": "balance",
                    "start_date": start.isoformat(),
                },
            )
            assert res.status_code == 201, res.text
            return res.json()

        first = await make(today - timedelta(days=20))
        second = await make(today - timedelta(days=10))
        assert first["loan_number"] == 1
        assert second["loan_number"] == 2

        # Register a loan dated BETWEEN the two.
        await make(today - timedelta(days=15))

        still_second = (
            await client.get(f"/api/v1/loans/{second['id']}", headers=inv)
        ).json()
        assert still_second["loan_number"] == 2, "numbers are assigned once, not ranked"


class TestTheRoundClearsAsYouCollect:
    """A collected customer leaves the round; an uncollected one stays.

    A balance loan has no due date, so it would otherwise sit on the list all
    day looking identical before and after a visit — a collector working a
    dozen customers cannot tell who is left.
    """

    async def test_a_collected_loan_drops_off_the_round(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        _, col, loan = await _setup(client, db_session, "60")

        my_day = (await client.get("/api/v1/payments/my-day", headers=col)).json()
        assert any(p["loan_id"] == loan["id"] for p in my_day["pickups"])

        await _collect(client, col, loan["id"], 500)

        my_day = (await client.get("/api/v1/payments/my-day", headers=col)).json()
        assert all(p["loan_id"] != loan["id"] for p in my_day["pickups"]), (
            "the visit is done, so it should no longer be on the round"
        )

    async def test_only_the_collected_customer_leaves(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Collecting from one customer must not disturb the others."""
        investor = await _make_user(db_session, "rinv@x.com")
        collector = await _make_user(db_session, "rcol@x.com", UserRole.COLLECTOR)
        inv = await _login(client, investor)
        col = await _login(client, collector)

        loans = []
        for n in range(3):
            customer = await _make_customer(db_session, f"6100000{n}0{n}")
            res = await client.post(
                "/api/v1/loans",
                headers=inv,
                json={
                    "customer_id": customer.id,
                    "collector_id": collector.id,
                    "principal": 10_000,
                    "interest_type": "pct",
                    "interest_value": 10,
                    "lending_model": "model_b",
                    "collection_mode": "balance",
                    "start_date": date.today().isoformat(),
                },
            )
            assert res.status_code == 201, res.text
            loans.append(res.json())

        my_day = (await client.get("/api/v1/payments/my-day", headers=col)).json()
        assert len(my_day["pickups"]) == 3

        await _collect(client, col, loans[1]["id"], 800)

        my_day = (await client.get("/api/v1/payments/my-day", headers=col)).json()
        remaining = {p["loan_id"] for p in my_day["pickups"]}
        assert remaining == {loans[0]["id"], loans[2]["id"]}, "only the visited one leaves"
        assert my_day["collected_today"] == 800

    async def test_a_missed_visit_stays_on_the_round(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Marking missed moves no money, so the customer is still owed a visit."""
        _, col, loan = await _setup(client, db_session, "61")
        res = await client.post(
            "/api/v1/payments/missed",
            headers=col,
            json={"loan_id": loan["id"], "reason": "Shop closed"},
        )
        assert res.status_code in (200, 201), res.text

        my_day = (await client.get("/api/v1/payments/my-day", headers=col)).json()
        pickup = next((p for p in my_day["pickups"] if p["loan_id"] == loan["id"]), None)
        assert pickup is not None, "a missed visit is not a collected visit"
        assert pickup["collected_today"] == 0
        assert pickup["missed_count"] == 1


class TestCollectorTrendEndpoint:
    """Per-collector collection trend, for the collector detail screen."""

    async def test_trend_covers_only_that_collector(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        investor = await _make_user(db_session, "tinv@x.com")
        one = await _make_user(db_session, "tcol1@x.com", UserRole.COLLECTOR)
        two = await _make_user(db_session, "tcol2@x.com", UserRole.COLLECTOR)
        inv = await _login(client, investor)
        col_one = await _login(client, one)
        col_two = await _login(client, two)
        today = date.today()

        async def loan_for(collector_id: str, phone: str) -> dict[str, Any]:
            customer = await _make_customer(db_session, phone)
            res = await client.post(
                "/api/v1/loans",
                headers=inv,
                json={
                    "customer_id": customer.id,
                    "collector_id": collector_id,
                    "principal": 20_000,
                    "interest_type": "pct",
                    "interest_value": 10,
                    "lending_model": "model_b",
                    "collection_mode": "balance",
                    "start_date": today.isoformat(),
                },
            )
            assert res.status_code == 201, res.text
            return res.json()

        loan_one = await loan_for(one.id, "5900000001")
        loan_two = await loan_for(two.id, "5900000002")
        await _collect(client, col_one, loan_one["id"], 1_500)
        await _collect(client, col_two, loan_two["id"], 9_000)

        trend = (
            await client.get(f"/api/v1/collectors/{one.id}/trend", headers=inv)
        ).json()
        total = sum(point["amount"] for point in trend)
        assert total == 1_500, "the other collector's ₹9,000 must not appear"
        assert len(trend) == 30, "defaults to the last 30 days"

    async def test_an_explicit_range_is_honoured(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        investor = await _make_user(db_session, "tinv2@x.com")
        collector = await _make_user(db_session, "tcol3@x.com", UserRole.COLLECTOR)
        inv = await _login(client, investor)
        today = date.today()
        res = await client.get(
            f"/api/v1/collectors/{collector.id}/trend"
            f"?start_date={(today - timedelta(days=6)).isoformat()}"
            f"&end_date={today.isoformat()}",
            headers=inv,
        )
        assert res.status_code == 200, res.text
        assert len(res.json()) == 7

    async def test_a_collector_cannot_read_another_collectors_trend(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        investor = await _make_user(db_session, "tinv3@x.com")
        one = await _make_user(db_session, "tcol4@x.com", UserRole.COLLECTOR)
        two = await _make_user(db_session, "tcol5@x.com", UserRole.COLLECTOR)
        await _login(client, investor)
        col_two = await _login(client, two)
        res = await client.get(f"/api/v1/collectors/{one.id}/trend", headers=col_two)
        assert res.status_code in (403, 404), res.text
