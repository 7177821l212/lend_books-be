"""Seed users for local development. Idempotent — safe to re-run.

Run with:  uv run --no-sync python -m src.data.seed
"""

import asyncio
import logging

from src.constants.enums import UserRole
from src.data.clients.postgres_client import AsyncSessionLocal
from src.data.models.postgres.user import User
from src.data.repositories.user_repository import UserRepository
from src.utils.security import hash_password

logger = logging.getLogger("seed")


USERS_TO_SEED: list[dict[str, str]] = [
    {
        "name": "Owner",
        "email": "owner@lendbook.app",
        "phone": "9000000000",
        "password": "owner123",
        "role": UserRole.INVESTOR.value,
    },
    {
        "name": "Ravi Kumar",
        "email": "ravi@lendbook.app",
        "phone": "9876500001",
        "password": "ravi123",
        "role": UserRole.COLLECTOR.value,
    },
    {
        "name": "Suresh M",
        "email": "suresh@lendbook.app",
        "phone": "9876500002",
        "password": "suresh123",
        "role": UserRole.COLLECTOR.value,
    },
    {
        "name": "Anita Sharma",
        "email": "anita@lendbook.app",
        "phone": "9876500003",
        "password": "anita123",
        "role": UserRole.COLLECTOR.value,
    },
    {
        "name": "Karthik V",
        "email": "karthik@lendbook.app",
        "phone": "9876500004",
        "password": "karthik123",
        "role": UserRole.COLLECTOR.value,
    },
    {
        "name": "Lakshmi R",
        "email": "lakshmi@lendbook.app",
        "phone": "9876500005",
        "password": "lakshmi123",
        "role": UserRole.COLLECTOR.value,
    },
    {
        "name": "Mani T",
        "email": "mani@lendbook.app",
        "phone": "9876500006",
        "password": "mani123",
        "role": UserRole.COLLECTOR.value,
    },
]


async def seed_users() -> int:
    """Insert any missing users. Returns count of newly created rows."""
    created = 0
    async with AsyncSessionLocal() as session:
        repo = UserRepository(session)
        for record in USERS_TO_SEED:
            existing = await repo.get_by_email(record["email"])
            if existing is not None:
                logger.info("user %s already exists — skipping", record["email"])
                continue
            user = User(
                name=record["name"],
                email=record["email"],
                phone=record["phone"],
                hashed_password=hash_password(record["password"]),
                role=record["role"],
                is_active=True,
            )
            await repo.create(user)
            created += 1
            logger.info("created %s (%s)", record["email"], record["role"])
        await session.commit()
    return created


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    created = await seed_users()
    print(f"✓ Seed complete — {created} new users created, {len(USERS_TO_SEED) - created} existed")


if __name__ == "__main__":
    asyncio.run(main())
