"""Integration tests for payment allocation and investor reschedule.

The behaviour under test is the fix for the PRAVEEN FISH report: several
collections taken on ONE day used to make future-dated schedule rows look as if
money had been collected on those future dates. Cash events and schedule rows
are now separate records joined by `payment_allocations`.
"""

from datetime import date, timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy import text
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
    user = User(
        email=email,
        name=email.split("@")[0],
        hashed_password=hash_password(password),
        role=role.value,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


async def _make_customer(db: AsyncSession, phone: str) -> Customer:
    customer = Customer(
        name=f"Cust {phone[-3:]}",
        phone=phone,
        location="X",
        risk_level="medium",
        is_blacklisted=False,
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
    client: AsyncClient,
    db: AsyncSession,
    suffix: str,
    *,
    principal: int = 10000,
    interest_value: float = 10,
    total_installments: int = 10,
) -> tuple[dict[str, str], dict[str, str], dict[str, Any]]:
    """Create investor + collector + customer + one active loan."""
    investor = await _make_user(db, f"inv{suffix}@x.com")
    collector = await _make_user(db, f"col{suffix}@x.com", UserRole.COLLECTOR)
    customer = await _make_customer(db, f"9{suffix.rjust(9, '0')}")
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
            "interest_value": interest_value,
            "lending_model": "model_b",
            "repayment_frequency": "daily",
            "total_installments": total_installments,
            "start_date": date.today().isoformat(),
        },
    )
    assert res.status_code == 201, res.text
    return inv_headers, col_headers, res.json()


async def _collect(
    client: AsyncClient, headers: dict[str, str], loan_id: str, amount: int
) -> dict[str, Any]:
    res = await client.post(
        "/api/v1/payments/collect",
        headers=headers,
        json={"loan_id": loan_id, "amount": amount, "mode": "CASH"},
    )
    assert res.status_code in (200, 201), res.text
    return res.json()


class TestAllocation:
    async def test_one_days_collections_never_mark_future_rows_collected(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The PRAVEEN FISH case: four ₹480 receipts taken on a single day.

        The money must spread across installments 1–8 as *coverage*, while every
        payment keeps the one real collection date and amount.
        """
        _, col_headers, loan = await _setup(
            client, db_session, "1", principal=20000, interest_value=20,
            total_installments=100,
        )
        assert loan["repayable"] == 24000

        for _ in range(4):
            await _collect(client, col_headers, loan["id"], 480)

        res = await client.get(f"/api/v1/payments/history?loan_id={loan['id']}", headers=col_headers)
        payments = res.json()["items"]
        assert len(payments) == 4
        # Every receipt is stored at its real value — none was split into
        # separate "collections" on the days its money happened to cover.
        assert [p["amount"] for p in payments] == [480, 480, 480, 480]
        assert len({p["collected_at"][:10] for p in payments}) == 1

        # ...and each receipt carries its own installment breakdown.
        assert sum(a["amount"] for p in payments for a in p["allocations"]) == 1920
        covered = {a["sequence"] for p in payments for a in p["allocations"]}
        assert covered == {1, 2, 3, 4, 5, 6, 7, 8}

        detail = (await client.get(f"/api/v1/loans/{loan['id']}", headers=col_headers)).json()
        rows = {i["sequence"]: i for i in detail["installments"]}
        assert all(rows[s]["status"] == "paid" for s in range(1, 9))
        assert rows[9]["paid_amount"] == 0, "row 9 was never touched"

    async def test_short_then_over_then_short_payments_carry_advance_credit(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """The worked example: ₹1,100/day for 10 days on an ₹11,000 loan."""
        _, col_headers, loan = await _setup(
            client, db_session, "2", principal=10000, interest_value=10,
            total_installments=10,
        )
        assert loan["repayable"] == 11000
        assert loan["installment_amount"] == 1100

        # Day 1: pays ₹1,000 against ₹1,100 due → ₹100 still owing on day 1.
        await _collect(client, col_headers, loan["id"], 1000)
        # Day 2: pays ₹2,000 → ₹100 clears day 1, ₹1,100 day 2, ₹800 advance.
        p2 = await _collect(client, col_headers, loan["id"], 2000)
        assert [(a["sequence"], a["amount"]) for a in p2["allocations"]] == [
            (1, 100),
            (2, 1100),
            (3, 800),
        ]
        # Day 3: only ₹300 of day 3 was left, so ₹500 leaves ₹200 for day 4.
        p3 = await _collect(client, col_headers, loan["id"], 500)
        assert [(a["sequence"], a["amount"]) for a in p3["allocations"]] == [
            (3, 300),
            (4, 200),
        ]

        detail = (await client.get(f"/api/v1/loans/{loan['id']}", headers=col_headers)).json()
        rows = {i["sequence"]: i for i in detail["installments"]}
        assert rows[3]["paid_amount"] == 1100 and rows[3]["status"] == "paid"
        assert rows[4]["paid_amount"] == 200 and rows[4]["status"] == "partial"
        assert detail["repaid"] == 3500

    async def test_marking_a_visit_missed_still_works(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A missed visit moves no cash, so it reports zero allocations."""
        _, col_headers, loan = await _setup(client, db_session, "3")
        first = sorted(loan["installments"], key=lambda i: i["sequence"])[0]
        res = await client.post(
            "/api/v1/payments/missed",
            headers=col_headers,
            json={
                "loan_id": loan["id"],
                "schedule_id": first["id"],
                "reason": "shop shut",
            },
        )
        assert res.status_code in (200, 201), res.text
        body = res.json()
        assert body["is_missed"] is True
        assert body["amount"] == 0
        assert body["allocations"] == []


class TestReschedulePreview:
    async def test_preview_writes_nothing_and_shows_both_plans(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        inv_headers, col_headers, loan = await _setup(client, db_session, "4")
        await _collect(client, col_headers, loan["id"], 2200)  # clears days 1-2

        res = await client.post(
            f"/api/v1/loans/{loan['id']}/reschedule/preview",
            headers=inv_headers,
            json={
                "reason": "Customer request",
                "mode": "same_installment",
                "installment_amount": 2200,
            },
        )
        assert res.status_code == 200, res.text
        preview = res.json()
        assert preview["remaining_balance"] == 8800
        assert len(preview["current"]) == 8
        assert len(preview["proposed"]) == 4
        assert preview["proposed_total"] == preview["current_total"] == 8800
        assert preview["proposed_end_date"] < preview["current_end_date"]

        # Nothing was persisted.
        detail = (await client.get(f"/api/v1/loans/{loan['id']}", headers=inv_headers)).json()
        assert len(detail["installments"]) == 10
        assert all(i["schedule_version"] == 1 for i in detail["installments"])
        assert (
            await client.get(f"/api/v1/loans/{loan['id']}/revisions", headers=inv_headers)
        ).json() == []

    async def test_same_end_date_keeps_the_finish_day(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        inv_headers, col_headers, loan = await _setup(client, db_session, "5")
        await _collect(client, col_headers, loan["id"], 1100)

        original_end = max(i["due_date"] for i in loan["installments"])
        res = await client.post(
            f"/api/v1/loans/{loan['id']}/reschedule/preview",
            headers=inv_headers,
            json={"reason": "Advance payment", "mode": "same_end_date"},
        )
        preview = res.json()
        assert preview["proposed_end_date"] == original_end
        assert len(preview["proposed"]) == 9
        assert sum(r["due_amount"] for r in preview["proposed"]) == 9900


class TestRescheduleCommit:
    async def test_paid_rows_and_collections_survive_a_reschedule(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        inv_headers, col_headers, loan = await _setup(client, db_session, "6")
        await _collect(client, col_headers, loan["id"], 3300)  # days 1-3 paid

        res = await client.post(
            f"/api/v1/loans/{loan['id']}/reschedule",
            headers=inv_headers,
            json={
                "reason": "Customer request",
                "mode": "same_installment",
                "installment_amount": 1540,
            },
        )
        assert res.status_code == 200, res.text
        detail = res.json()

        active = [i for i in detail["installments"] if i["is_active"]]
        replaced = [i for i in detail["installments"] if not i["is_active"]]
        assert len(replaced) == 7, "the 7 unpaid rows were replaced"
        assert all(r["replaced_at"] is not None for r in replaced)
        paid = [i for i in active if i["status"] == "paid"]
        assert len(paid) == 3, "paid rows are untouched"
        assert all(i["schedule_version"] == 1 for i in paid)

        new_rows = [i for i in active if i["schedule_version"] == 2]
        assert len(new_rows) == 5
        assert sum(i["due_amount"] for i in new_rows) == 7700
        assert detail["outstanding"] == 7700
        assert detail["total_installments"] == 8

        # Sequences never collide between a replaced row and its replacement.
        assert len({i["sequence"] for i in detail["installments"]}) == len(
            detail["installments"]
        )

        # The cash ledger is untouched by the reschedule.
        payments = (
            await client.get(f"/api/v1/payments/history?loan_id={loan['id']}", headers=inv_headers)
        ).json()["items"]
        assert [p["amount"] for p in payments] == [3300]
        assert sum(a["amount"] for a in payments[0]["allocations"]) == 3300

    async def test_revision_records_who_why_and_when(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        inv_headers, col_headers, loan = await _setup(client, db_session, "7")
        await _collect(client, col_headers, loan["id"], 1100)
        await client.post(
            f"/api/v1/loans/{loan['id']}/reschedule",
            headers=inv_headers,
            json={"reason": "Advance payment", "mode": "same_end_date"},
        )
        revisions = (
            await client.get(f"/api/v1/loans/{loan['id']}/revisions", headers=inv_headers)
        ).json()
        assert len(revisions) == 1
        assert revisions[0]["version"] == 2
        assert revisions[0]["reason"] == "Advance payment"
        assert revisions[0]["created_by_name"] == "inv7"
        assert revisions[0]["effective_from"]

    async def test_collections_after_a_reschedule_hit_the_new_rows(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        inv_headers, col_headers, loan = await _setup(client, db_session, "8")
        await _collect(client, col_headers, loan["id"], 1100)
        await client.post(
            f"/api/v1/loans/{loan['id']}/reschedule",
            headers=inv_headers,
            json={
                "reason": "Customer request",
                "mode": "same_installment",
                "installment_amount": 9900,
            },
        )
        payment = await _collect(client, col_headers, loan["id"], 9900)
        assert sum(a["amount"] for a in payment["allocations"]) == 9900

        detail = (await client.get(f"/api/v1/loans/{loan['id']}", headers=inv_headers)).json()
        assert detail["status"] == "closed"
        assert detail["outstanding"] == 0

    async def test_manual_plan_must_match_the_remaining_balance(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        inv_headers, col_headers, loan = await _setup(client, db_session, "9")
        await _collect(client, col_headers, loan["id"], 1100)
        tomorrow = date.today() + timedelta(days=1)
        res = await client.post(
            f"/api/v1/loans/{loan['id']}/reschedule",
            headers=inv_headers,
            json={
                "reason": "Customer request",
                "mode": "manual",
                "installments": [
                    {"due_date": tomorrow.isoformat(), "due_amount": 5000}
                ],
            },
        )
        assert res.status_code == 422
        assert "9900" in res.text

    async def test_collector_cannot_reschedule(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        _, col_headers, loan = await _setup(client, db_session, "10")
        res = await client.post(
            f"/api/v1/loans/{loan['id']}/reschedule",
            headers=col_headers,
            json={"reason": "Customer request", "mode": "same_end_date"},
        )
        assert res.status_code == 403

    async def test_collector_cannot_preview_either(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        _, col_headers, loan = await _setup(client, db_session, "11")
        res = await client.post(
            f"/api/v1/loans/{loan['id']}/reschedule/preview",
            headers=col_headers,
            json={"reason": "Customer request", "mode": "same_end_date"},
        )
        assert res.status_code == 403


class TestBalancesAfterRescheduleOfPartialRow:
    """A replaced PARTIAL row keeps its paid_amount on the inactive row.

    The replacement plan only covers `due - paid`, so any sum of CASH COLLECTED
    must include inactive rows. Filtering them out overstates what the customer
    still owes by exactly the partial amount.
    """

    async def test_every_surface_agrees_on_outstanding_and_repaid(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        inv_headers, col_headers, loan = await _setup(client, db_session, "12")
        # ₹500 against a ₹1,100 first installment — a genuine partial.
        await _collect(client, col_headers, loan["id"], 500)
        res = await client.post(
            f"/api/v1/loans/{loan['id']}/reschedule",
            headers=inv_headers,
            json={"reason": "Customer request", "mode": "same_end_date"},
        )
        assert res.status_code == 200, res.text

        # ₹11,000 repayable, ₹500 collected → ₹10,500 still owed, everywhere.
        detail = res.json()
        assert detail["outstanding"] == 10_500, "loan detail outstanding"
        assert detail["repaid"] == 500, "loan detail repaid"

        customer = (
            await client.get(
                f"/api/v1/customers/{loan['customer_id']}", headers=inv_headers
            )
        ).json()
        assert customer["total_outstanding"] == 10_500, "customer detail outstanding"

        listed = (
            await client.get("/api/v1/customers?page_size=100", headers=inv_headers)
        ).json()["items"]
        row = next(c for c in listed if c["id"] == loan["customer_id"])
        assert row["total_outstanding"] == 10_500, "customer list outstanding"
        assert row["active_loan_count"] == 1, "customer list active loan count"

        kpis = (await client.get("/api/v1/dashboard", headers=inv_headers)).json()["kpis"]
        assert kpis["outstanding"] == 10_500, "dashboard outstanding"
        assert kpis["collected_lifetime"] == 500, "dashboard collected lifetime"


class TestMissedVisitAccounting:
    async def test_a_missed_visit_does_not_double_the_outstanding(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Marking missed appends a replacement row; only one of the two counts."""
        inv_headers, col_headers, loan = await _setup(client, db_session, "13")
        rows = sorted(loan["installments"], key=lambda i: i["sequence"])
        res = await client.post(
            "/api/v1/payments/missed",
            headers=col_headers,
            json={"loan_id": loan["id"], "schedule_id": rows[0]["id"], "reason": "shut"},
        )
        assert res.status_code in (200, 201), res.text

        detail = (await client.get(f"/api/v1/loans/{loan['id']}", headers=inv_headers)).json()
        # Nothing was collected, so the full ₹11,000 is still owed — not ₹12,100.
        assert detail["outstanding"] == 11_000
        assert detail["repaid"] == 0
        assert detail["total_installments"] == 11, "one replacement row appended"

    async def test_a_replaced_row_cannot_be_marked_missed(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A collector on a stale pickup list must not resurrect a replaced row."""
        inv_headers, col_headers, loan = await _setup(client, db_session, "14")
        stale = sorted(loan["installments"], key=lambda i: i["sequence"])[3]
        await client.post(
            f"/api/v1/loans/{loan['id']}/reschedule",
            headers=inv_headers,
            json={"reason": "Customer request", "mode": "same_end_date"},
        )
        res = await client.post(
            "/api/v1/payments/missed",
            headers=col_headers,
            json={"loan_id": loan["id"], "schedule_id": stale["id"], "reason": "shut"},
        )
        assert res.status_code == 404, res.text

        detail = (await client.get(f"/api/v1/loans/{loan['id']}", headers=inv_headers)).json()
        assert detail["outstanding"] == 11_000, "no phantom installment was appended"
        assert detail["total_installments"] == 10


class TestShortPaymentVsMissedVisit:
    """₹20,000 @10% Model B = ₹22,000 over 10 daily visits of ₹2,200.

    A SHORT payment and a MISSED visit are different events with different
    rules, and a single visit cannot be both.
    """

    async def test_a_visit_that_took_money_cannot_also_be_marked_missed(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        inv_headers, col_headers, loan = await _setup(
            client, db_session, "15", principal=20_000, interest_value=10,
            total_installments=10,
        )
        assert loan["repayable"] == 22_000
        rows = sorted(loan["installments"], key=lambda i: i["sequence"])

        await _collect(client, col_headers, loan["id"], 1_100)  # half of ₹2,200
        res = await client.post(
            "/api/v1/payments/missed",
            headers=col_headers,
            json={"loan_id": loan["id"], "schedule_id": rows[0]["id"], "reason": "shut"},
        )
        assert res.status_code == 409, res.text
        assert "1,100" in res.text

        detail = (await client.get(f"/api/v1/loans/{loan['id']}", headers=inv_headers)).json()
        assert detail["total_installments"] == 10, "no catch-up row was created"
        assert detail["repaid"] == 1_100
        assert detail["outstanding"] == 20_900

    async def test_a_short_payment_leaves_the_balance_on_its_own_date(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """₹1,100 against a ₹2,200 visit leaves ₹1,100 owed on THAT date —
        it is never pushed onto the next installment or to the end."""
        inv_headers, col_headers, loan = await _setup(
            client, db_session, "16", principal=20_000, interest_value=10,
            total_installments=10,
        )
        await _collect(client, col_headers, loan["id"], 1_100)

        detail = (await client.get(f"/api/v1/loans/{loan['id']}", headers=inv_headers)).json()
        rows = {i["sequence"]: i for i in detail["installments"]}
        assert rows[1]["paid_amount"] == 1_100
        assert rows[1]["due_amount"] - rows[1]["paid_amount"] == 1_100, "shortfall stays here"
        assert rows[1]["status"] == "partial"
        assert rows[2]["paid_amount"] == 0, "the next visit is untouched"
        assert rows[2]["due_amount"] == 2_200
        assert detail["total_installments"] == 10

        # The collector's worklist asks for the ₹1,100 shortfall, not ₹2,200.
        my_day = (await client.get("/api/v1/payments/my-day", headers=col_headers)).json()
        first = next(p for p in my_day["pickups"] if p["sequence"] == 1)
        assert first["due_amount"] == 1_100

    async def test_a_genuinely_missed_visit_carries_the_whole_amount_forward(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        inv_headers, col_headers, loan = await _setup(
            client, db_session, "17", principal=20_000, interest_value=10,
            total_installments=10,
        )
        rows = sorted(loan["installments"], key=lambda i: i["sequence"])
        res = await client.post(
            "/api/v1/payments/missed",
            headers=col_headers,
            json={"loan_id": loan["id"], "schedule_id": rows[0]["id"], "reason": "shut"},
        )
        assert res.status_code in (200, 201), res.text

        detail = (await client.get(f"/api/v1/loans/{loan['id']}", headers=inv_headers)).json()
        carried = [i for i in detail["installments"] if i["sequence"] > 10]
        assert len(carried) == 1
        assert carried[0]["due_amount"] == 2_200, "nothing was collected, so all of it moves"
        assert detail["total_installments"] == 11
        assert detail["repaid"] == 0
        assert detail["outstanding"] == 22_000

        # The missed amount is NOT chased again on the next round — it now lives
        # at the end of the schedule.
        my_day = (await client.get("/api/v1/payments/my-day", headers=col_headers)).json()
        assert all(p["sequence"] != 1 for p in my_day["pickups"])

    async def test_advance_credit_does_not_block_a_missed_visit(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A row can hold credit from an EARLIER lump sum and still be missed
        today — the guard is about money taken on this visit, not any money."""
        inv_headers, col_headers, loan = await _setup(
            client, db_session, "18", principal=20_000, interest_value=10,
            total_installments=10,
        )
        # ₹3,300 clears visit #1 and leaves ₹1,100 of advance credit on #2.
        await _collect(client, col_headers, loan["id"], 3_300)
        rows = sorted(loan["installments"], key=lambda i: i["sequence"])

        # Backdate the receipt so it is no longer "today" for visit #2.
        await db_session.execute(
            text(
                "UPDATE payments SET collected_at = collected_at - INTERVAL '2 days' "
                "WHERE loan_id = :loan_id"
            ),
            {"loan_id": loan["id"]},
        )
        res = await client.post(
            "/api/v1/payments/missed",
            headers=col_headers,
            json={"loan_id": loan["id"], "schedule_id": rows[1]["id"], "reason": "shut"},
        )
        assert res.status_code in (200, 201), res.text

        detail = (await client.get(f"/api/v1/loans/{loan['id']}", headers=inv_headers)).json()
        carried = [i for i in detail["installments"] if i["sequence"] > 10]
        assert carried[0]["due_amount"] == 1_100, "only the UNCREDITED part moves"
        assert detail["repaid"] == 3_300, "the advance credit is still collected cash"
        assert detail["repaid"] + detail["outstanding"] == 22_000

    async def test_a_loan_with_a_missed_visit_can_still_close(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A MISSED row is settled history once carried forward, so it must not
        block closure when every collectible row is paid."""
        inv_headers, col_headers, loan = await _setup(
            client, db_session, "19", principal=20_000, interest_value=10,
            total_installments=10,
        )
        rows = sorted(loan["installments"], key=lambda i: i["sequence"])
        await client.post(
            "/api/v1/payments/missed",
            headers=col_headers,
            json={"loan_id": loan["id"], "schedule_id": rows[0]["id"], "reason": "shut"},
        )
        await _collect(client, col_headers, loan["id"], 22_000)

        detail = (await client.get(f"/api/v1/loans/{loan['id']}", headers=inv_headers)).json()
        assert detail["repaid"] == 22_000
        assert detail["outstanding"] == 0
        assert detail["status"] == "closed"


class TestOverpayment:
    async def test_overpayment_flows_forward_as_advance_credit(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        inv_headers, col_headers, loan = await _setup(
            client, db_session, "20", principal=20_000, interest_value=10,
            total_installments=10,
        )
        # ₹5,000 = visits #1 and #2 in full, plus ₹600 sitting on #3.
        payment = await _collect(client, col_headers, loan["id"], 5_000)
        assert [(a["sequence"], a["amount"]) for a in payment["allocations"]] == [
            (1, 2_200),
            (2, 2_200),
            (3, 600),
        ]
        detail = (await client.get(f"/api/v1/loans/{loan['id']}", headers=inv_headers)).json()
        rows = {i["sequence"]: i for i in detail["installments"]}
        assert rows[3]["paid_amount"] == 600 and rows[3]["status"] == "partial"
        assert detail["repaid"] == 5_000
        assert detail["outstanding"] == 17_000

        # When #3 comes due the collector will be asked for the ₹1,600 balance,
        # not the full ₹2,200 — the credit is already sitting on the row.
        assert rows[3]["due_amount"] - rows[3]["paid_amount"] == 1_600
        # Visits already covered drop off the worklist entirely.
        my_day = (await client.get("/api/v1/payments/my-day", headers=col_headers)).json()
        assert all(p["sequence"] not in {1, 2} for p in my_day["pickups"])

    async def test_cannot_collect_more_than_the_loan_still_owes(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        _, col_headers, loan = await _setup(
            client, db_session, "21", principal=20_000, interest_value=10,
            total_installments=10,
        )
        res = await client.post(
            "/api/v1/payments/collect",
            headers=col_headers,
            json={"loan_id": loan["id"], "amount": 22_001, "mode": "CASH"},
        )
        assert res.status_code == 409
