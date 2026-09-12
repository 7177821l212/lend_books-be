"""Integration tests for /customers/* endpoints."""

from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants.enums import (
    InterestType,
    LendingModel,
    LoanStatus,
    RepaymentFrequency,
    UserRole,
)
from src.data.models.postgres.customer import Customer
from src.data.models.postgres.loan import Loan
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


async def _make_customer(
    db: AsyncSession,
    name: str = "Test Customer",
    phone: str = "9999900001",
    blacklisted: bool = False,
) -> Customer:
    c = Customer(
        name=name,
        phone=phone,
        location="Coimbatore",
        risk_level="medium",
        is_blacklisted=blacklisted,
    )
    db.add(c)
    await db.flush()
    await db.refresh(c)
    return c


async def _make_active_loan(
    db: AsyncSession, customer_id: str, collector_id: str
) -> Loan:
    loan = Loan(
        customer_id=customer_id,
        collector_id=collector_id,
        principal=10000,
        interest_type=InterestType.PCT.value,
        interest_value=10.0,
        lending_model=LendingModel.MODEL_A.value,
        disbursed=9000,
        repayable=10000,
        profit=1000,
        repayment_frequency=RepaymentFrequency.DAILY.value,
        total_installments=10,
        installment_amount=1000,
        start_date=date.today(),
        status=LoanStatus.ACTIVE.value,
    )
    db.add(loan)
    await db.flush()
    await db.refresh(loan)
    return loan


async def _login_as(
    client: AsyncClient, user: User, password: str = "pw12345"
) -> dict[str, str]:
    res = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": password}
    )
    assert res.status_code == 200
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.integration
class TestCustomerList:
    async def test_investor_sees_all_customers(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        investor = await _make_user(db_session, "inv1@x.com")
        await _make_customer(db_session, "Alice", "9000000001")
        await _make_customer(db_session, "Bob", "9000000002")
        await _make_customer(db_session, "Carol", "9000000003")

        headers = await _login_as(client, investor)
        res = await client.get("/api/v1/customers", headers=headers)
        assert res.status_code == 200
        body = res.json()
        assert body["total"] == 3
        assert len(body["items"]) == 3

    async def test_collector_sees_only_assigned_customers(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        collector1 = await _make_user(db_session, "c1@x.com", role=UserRole.COLLECTOR)
        collector2 = await _make_user(db_session, "c2@x.com", role=UserRole.COLLECTOR)
        cust_a = await _make_customer(db_session, "Alice", "9000000010")
        cust_b = await _make_customer(db_session, "Bob", "9000000011")
        await _make_customer(db_session, "Carol", "9000000012")  # unassigned
        await _make_active_loan(db_session, cust_a.id, collector1.id)
        await _make_active_loan(db_session, cust_b.id, collector2.id)

        headers = await _login_as(client, collector1)
        res = await client.get("/api/v1/customers", headers=headers)
        assert res.status_code == 200
        body = res.json()
        assert body["total"] == 1
        assert body["items"][0]["name"] == "Alice"

    async def test_search_filters_by_name(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        investor = await _make_user(db_session, "inv2@x.com")
        await _make_customer(db_session, "Murugan Textiles", "9000000021")
        await _make_customer(db_session, "Lakshmi Stores", "9000000022")

        headers = await _login_as(client, investor)
        res = await client.get("/api/v1/customers?search=Murugan", headers=headers)
        assert res.status_code == 200
        assert res.json()["total"] == 1

    async def test_filter_blacklisted(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        investor = await _make_user(db_session, "inv3@x.com")
        await _make_customer(db_session, "Active 1", "9000000031")
        await _make_customer(db_session, "Banned 1", "9000000032", blacklisted=True)

        headers = await _login_as(client, investor)
        res = await client.get("/api/v1/customers?status=blacklisted", headers=headers)
        assert res.status_code == 200
        body = res.json()
        assert body["total"] == 1
        assert body["items"][0]["name"] == "Banned 1"
        assert body["items"][0]["is_blacklisted"] is True

    async def test_pagination(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        investor = await _make_user(db_session, "inv4@x.com")
        for i in range(5):
            await _make_customer(db_session, f"Cust {i}", f"900000004{i}")

        headers = await _login_as(client, investor)
        res = await client.get("/api/v1/customers?page=1&page_size=2", headers=headers)
        body = res.json()
        assert body["total"] == 5
        assert len(body["items"]) == 2
        assert body["has_next"] is True

        res2 = await client.get("/api/v1/customers?page=3&page_size=2", headers=headers)
        body2 = res2.json()
        assert len(body2["items"]) == 1
        assert body2["has_next"] is False

    async def test_list_includes_persisted_profile_photo(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        investor = await _make_user(db_session, "inv-photo-list@x.com")
        customer = await _make_customer(db_session, "Photo Customer", "9000000049")
        customer.photo_url = "photos/customer-profile.png"
        await db_session.flush()

        headers = await _login_as(client, investor)
        response = await client.get("/api/v1/customers", headers=headers)

        assert response.status_code == 200
        item = next(
            item for item in response.json()["items"] if item["id"] == customer.id
        )
        assert item["photo_url"] == "photos/customer-profile.png"


@pytest.mark.integration
class TestCustomerCreate:
    async def test_investor_can_create_customer(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        investor = await _make_user(db_session, "inv-c1@x.com")
        headers = await _login_as(client, investor)
        res = await client.post(
            "/api/v1/customers",
            headers=headers,
            json={
                "name": "New Customer",
                "phone": "9000000050",
                "location": "Salem",
                "risk_level": "low",
            },
        )
        assert res.status_code == 201
        body = res.json()
        assert body["name"] == "New Customer"
        assert body["risk_level"] == "low"
        assert body["is_blacklisted"] is False

    async def test_collector_cannot_create_customer(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        collector = await _make_user(db_session, "c-c1@x.com", role=UserRole.COLLECTOR)
        headers = await _login_as(client, collector)
        res = await client.post(
            "/api/v1/customers",
            headers=headers,
            json={"name": "Should Fail", "phone": "9000000060"},
        )
        assert res.status_code == 403

    async def test_duplicate_phone_returns_409(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        investor = await _make_user(db_session, "inv-c2@x.com")
        await _make_customer(db_session, "Existing", "9000000070")
        headers = await _login_as(client, investor)
        res = await client.post(
            "/api/v1/customers",
            headers=headers,
            json={"name": "Dup", "phone": "9000000070"},
        )
        assert res.status_code == 409

    async def test_duplicate_phone_whitespace_variant_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Whitespace / dash variants of an existing phone must still collide."""
        investor = await _make_user(db_session, "inv-c3@x.com")
        await _make_customer(db_session, "Existing", "9000000071")
        headers = await _login_as(client, investor)
        res = await client.post(
            "/api/v1/customers",
            headers=headers,
            json={"name": "Dup formatted", "phone": "900-000-0071"},
        )
        assert res.status_code == 409

    async def test_update_phone_to_existing_returns_409(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        investor = await _make_user(db_session, "inv-c4@x.com")
        await _make_customer(db_session, "First", "9000000072")
        second = await _make_customer(db_session, "Second", "9000000073")
        headers = await _login_as(client, investor)
        res = await client.patch(
            f"/api/v1/customers/{second.id}",
            headers=headers,
            json={"phone": "9000000072"},
        )
        assert res.status_code == 409


@pytest.mark.integration
class TestCustomerBlacklist:
    async def test_investor_can_blacklist(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        investor = await _make_user(db_session, "inv-bl@x.com")
        cust = await _make_customer(db_session, "X", "9000000080")
        headers = await _login_as(client, investor)
        res = await client.post(
            f"/api/v1/customers/{cust.id}/blacklist",
            headers=headers,
            json={"reason": "Fraud"},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["is_blacklisted"] is True
        assert body["blacklist_reason"] == "Fraud"

    async def test_collector_cannot_blacklist(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        collector = await _make_user(db_session, "c-bl@x.com", role=UserRole.COLLECTOR)
        cust = await _make_customer(db_session, "X", "9000000081")
        headers = await _login_as(client, collector)
        res = await client.post(
            f"/api/v1/customers/{cust.id}/blacklist",
            headers=headers,
            json={"reason": "Fraud"},
        )
        assert res.status_code == 403


@pytest.mark.integration
class TestCustomerGet:
    async def test_get_includes_persisted_profile_photo(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        investor = await _make_user(db_session, "inv-photo-get@x.com")
        customer = await _make_customer(db_session, "Photo Customer", "9000000089")
        customer.photo_url = "photos/customer-profile.png"
        await db_session.flush()

        headers = await _login_as(client, investor)
        response = await client.get(f"/api/v1/customers/{customer.id}", headers=headers)

        assert response.status_code == 200
        assert response.json()["photo_url"] == "photos/customer-profile.png"

    async def test_get_nonexistent_returns_404(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        investor = await _make_user(db_session, "inv-get1@x.com")
        headers = await _login_as(client, investor)
        res = await client.get("/api/v1/customers/nonexistent-id", headers=headers)
        assert res.status_code == 404

    async def test_collector_cannot_view_unassigned_customer(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        collector = await _make_user(
            db_session, "c-get1@x.com", role=UserRole.COLLECTOR
        )
        cust = await _make_customer(db_session, "Stranger", "9000000090")
        headers = await _login_as(client, collector)
        res = await client.get(f"/api/v1/customers/{cust.id}", headers=headers)
        assert res.status_code == 403


@pytest.mark.integration
class TestCustomerDelete:
    async def test_delete_with_closed_loan_soft_deletes(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """Regression test: deleting a customer with a non-active (e.g. closed)
        loan used to hard-delete the row and hit the loans.customer_id NOT NULL
        constraint. Soft delete avoids touching the loans table entirely."""
        investor = await _make_user(db_session, "inv-del1@x.com")
        collector = await _make_user(
            db_session, "c-del1@x.com", role=UserRole.COLLECTOR
        )
        cust = await _make_customer(db_session, "Closed Loan Customer", "9000000100")
        loan = await _make_active_loan(db_session, cust.id, collector.id)
        loan.status = LoanStatus.CLOSED.value
        await db_session.flush()

        headers = await _login_as(client, investor)
        res = await client.delete(f"/api/v1/customers/{cust.id}", headers=headers)
        assert res.status_code == 204

        # Soft-deleted customer is no longer reachable via the API
        res = await client.get(f"/api/v1/customers/{cust.id}", headers=headers)
        assert res.status_code == 404

        await db_session.refresh(cust)
        assert cust.is_deleted is True
        assert cust.deleted_at is not None

    async def test_delete_blocked_with_active_loan(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        investor = await _make_user(db_session, "inv-del2@x.com")
        collector = await _make_user(
            db_session, "c-del2@x.com", role=UserRole.COLLECTOR
        )
        cust = await _make_customer(db_session, "Active Loan Customer", "9000000101")
        await _make_active_loan(db_session, cust.id, collector.id)

        headers = await _login_as(client, investor)
        res = await client.delete(f"/api/v1/customers/{cust.id}", headers=headers)
        assert res.status_code == 409

    async def test_deleted_customer_excluded_from_list(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        investor = await _make_user(db_session, "inv-del3@x.com")
        cust = await _make_customer(db_session, "Gone", "9000000102")

        headers = await _login_as(client, investor)
        res = await client.delete(f"/api/v1/customers/{cust.id}", headers=headers)
        assert res.status_code == 204

        res = await client.get("/api/v1/customers", headers=headers)
        assert res.status_code == 200
        ids = [c["id"] for c in res.json()["items"]]
        assert cust.id not in ids


@pytest.mark.integration
class TestCustomerDocuments:
    async def test_investor_uploads_document_to_storage_and_it_is_listed(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        investor = await _make_user(db_session, "inv-doc@x.com")
        customer = await _make_customer(db_session, "Document customer", "9000000103")
        headers = await _login_as(client, investor)
        saved: dict[str, object] = {}

        def save_bytes(content: bytes, content_type: str, object_name: str) -> str:
            saved.update(
                content=content, content_type=content_type, object_name=object_name
            )
            return object_name

        monkeypatch.setattr(
            "src.core.services.customer_document_service.gcs.save_bytes", save_bytes
        )
        response = await client.post(
            f"/api/v1/customers/{customer.id}/documents",
            headers=headers,
            data={"doc_type": "ID Proof"},
            files={"file": ("identity.pdf", b"%PDF-1.7 test", "application/pdf")},
        )

        assert response.status_code == 201
        body = response.json()
        assert body["doc_type"] == "ID Proof"
        assert body["file_url"].startswith(f"documents/{customer.id}/id-proof/")
        assert saved["content"] == b"%PDF-1.7 test"
        assert saved["content_type"] == "application/pdf"

        listed = await client.get(
            f"/api/v1/customers/{customer.id}/documents", headers=headers
        )
        assert listed.status_code == 200
        assert [document["id"] for document in listed.json()] == [body["id"]]

    async def test_document_type_cannot_escape_its_storage_prefix(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        investor = await _make_user(db_session, "inv-doc-invalid@x.com")
        customer = await _make_customer(db_session, "Invalid document", "9000000104")
        headers = await _login_as(client, investor)

        response = await client.post(
            f"/api/v1/customers/{customer.id}/documents",
            headers=headers,
            data={"doc_type": "../../photos"},
            files={"file": ("identity.pdf", b"%PDF-1.7 test", "application/pdf")},
        )
        assert response.status_code == 422
