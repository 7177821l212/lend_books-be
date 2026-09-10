"""Pytest fixtures — runs against `lendbook_test` DB on port 5435."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import NullPool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.api.rest.app import create_app
from src.api.rest.dependencies import get_db
from src.api.middleware.rate_limit import limiter
from src.data.models.postgres import Base  # noqa — imports all models

TEST_DATABASE_URL = "postgresql+asyncpg://lendbook:lendbook@localhost:5435/lendbook_test"

engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
TestSession = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def db_session(setup_db):
    """Truncate tables, then yield a session that commits at the end."""
    async with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())
    async with TestSession() as session:
        yield session
        await session.commit()


@pytest.fixture
async def client(db_session: AsyncSession):
    limiter.reset()
    app = create_app()

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
