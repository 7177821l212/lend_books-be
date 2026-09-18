"""Seed a demo customer + loans for manually exercising the schedule UI.

Development only. Idempotent — re-running replaces the demo customer and its
loans, leaving every other record alone.

Everything is created through the real services, so the collections it records
produce genuine `payment_allocations` rather than hand-written rows.

Run with:  uv run --no-sync python -m src.data.seed_demo
       or: .venv/bin/python -m src.data.seed_demo
"""

import asyncio
import logging

from sqlalchemy import select

from src.constants.enums import (
    InterestType,
    LendingModel,
    PaymentMode,
    RepaymentFrequency,
    UserRole,
)
from src.core.services.loan_service import LoanService
from src.core.services.payment_service import PaymentService
from src.config.settings import settings
from src.data.clients.postgres_client import AsyncSessionLocal
from src.data.models.postgres.customer import Customer
from src.data.models.postgres.loan import Loan
from src.data.models.postgres.user import User
from src.schemas.loan import LoanCreate
from src.schemas.payment import CollectRequest
from src.utils.security import hash_password
from src.utils.time import business_today

logger = logging.getLogger("seed_demo")

COLLECTOR_EMAIL = "collector@lendbook.app"
COLLECTOR_PASSWORD = "collect123"
DEMO_PHONE = "9876500001"


async def _get_or_create_collector(session) -> User:
    result = await session.execute(select(User).where(User.email == COLLECTOR_EMAIL))
    collector = result.scalar_one_or_none()
    if collector is not None:
        return collector
    collector = User(
        name="Ravi (Collector)",
        email=COLLECTOR_EMAIL,
        phone="9000000001",
        hashed_password=hash_password(COLLECTOR_PASSWORD),
        role=UserRole.COLLECTOR.value,
        is_active=True,
    )
    session.add(collector)
    await session.flush()
    logger.info("created collector %s", COLLECTOR_EMAIL)
    return collector


async def _get_investor(session) -> User:
    result = await session.execute(
        select(User).where(User.role == UserRole.INVESTOR.value).order_by(User.created_at)
    )
    investor = result.scalars().first()
    if investor is None:
        raise SystemExit("No investor user found — run `python -m src.data.seed` first.")
    return investor


async def _reset_demo_customer(session) -> Customer:
    """Drop any previous demo customer and its loans, then recreate it."""
    result = await session.execute(select(Customer).where(Customer.phone == DEMO_PHONE))
    existing = result.scalar_one_or_none()
    if existing is not None:
        loans = (
            await session.execute(select(Loan).where(Loan.customer_id == existing.id))
        ).scalars()
        for loan in loans:
            await session.delete(loan)
        await session.delete(existing)
        await session.flush()
        logger.info("cleared previous demo customer")

    customer = Customer(
        name="PRAVEEN FISH",
        phone=DEMO_PHONE,
        location="Market Road",
        risk_level="medium",
        is_blacklisted=False,
    )
    session.add(customer)
    await session.flush()
    return customer


def _require_dev_environment() -> None:
    """Refuse to run anywhere but development.

    This script hard-deletes any customer on DEMO_PHONE together with their
    loans, payments and allocations, and provisions a collector login with a
    known password. Both are fine locally and unacceptable anywhere real, so the
    docstring is enforced rather than trusted.
    """
    env = settings.APP_ENV.strip().lower()
    if env != "development":
        raise SystemExit(
            f"refusing to run demo seed with APP_ENV={settings.APP_ENV!r}; "
            "this script deletes customer data and creates a known-password login"
        )


async def seed_demo() -> None:
    _require_dev_environment()
    async with AsyncSessionLocal() as session:
        investor = await _get_investor(session)
        collector = await _get_or_create_collector(session)
        customer = await _reset_demo_customer(session)

        investor_ctx = {"sub": investor.id, "role": UserRole.INVESTOR.value}
        collector_ctx = {"sub": collector.id, "role": UserRole.COLLECTOR.value}
        loans = LoanService(session)
        payments = PaymentService(session)
        today = business_today()

        # Loan 1 — the reported case: 20,000 principal repayable as 24,000 over
        # 100 daily visits of 240, with four separate 480 collections taken today.
        reported = await loans.create(
            investor_ctx,
            LoanCreate(
                customer_id=customer.id,
                collector_id=collector.id,
                principal=20_000,
                interest_type=InterestType.PCT,
                interest_value=20,
                lending_model=LendingModel.MODEL_B,
                repayment_frequency=RepaymentFrequency.DAILY,
                total_installments=100,
                start_date=today,
            ),
        )
        for _ in range(4):
            await payments.collect(
                collector_ctx,
                CollectRequest(loan_id=reported.id, amount=480, mode=PaymentMode.CASH),
            )

        # Loan 2 — the short/over/short example: 1,100 a day for 10 days, paid
        # 1,000 then 2,000 then 500, which leaves advance credit sitting on a
        # future row without claiming money arrived there.
        example = await loans.create(
            investor_ctx,
            LoanCreate(
                customer_id=customer.id,
                collector_id=collector.id,
                principal=10_000,
                interest_type=InterestType.PCT,
                interest_value=10,
                lending_model=LendingModel.MODEL_B,
                repayment_frequency=RepaymentFrequency.DAILY,
                total_installments=10,
                start_date=today,
            ),
        )
        for amount in (1_000, 2_000, 500):
            await payments.collect(
                collector_ctx,
                CollectRequest(loan_id=example.id, amount=amount, mode=PaymentMode.CASH),
            )

        await session.commit()

    print("✓ Demo data ready")
    print(f"  Customer : PRAVEEN FISH ({DEMO_PHONE})")
    print("  Loan 1   : ₹20,000 → ₹24,000, 100 × ₹240 — four ₹480 collections today")
    print("  Loan 2   : ₹10,000 → ₹11,000, 10 × ₹1,100 — ₹1,000 / ₹2,000 / ₹500")
    print(f"  Collector: {COLLECTOR_EMAIL} / {COLLECTOR_PASSWORD}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    asyncio.run(seed_demo())
