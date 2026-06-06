"""Collector service — list and create collectors."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants.enums import UserRole
from src.core.exceptions.base import ConflictError, ForbiddenError
from src.data.models.postgres.user import User
from src.schemas.collector import CollectorCreate, CollectorResponse
from src.utils.security import hash_password


class CollectorService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _require_investor(self, current_user: dict) -> None:
        if current_user.get("role") != UserRole.INVESTOR.value:
            raise ForbiddenError("only investor can manage collectors")

    async def list(self, current_user: dict) -> list[CollectorResponse]:
        self._require_investor(current_user)
        result = await self.session.execute(
            select(User)
            .where(User.role == UserRole.COLLECTOR.value, User.is_active.is_(True))
            .order_by(User.name)
        )
        return [CollectorResponse.model_validate(u) for u in result.scalars()]

    async def create(self, current_user: dict, body: CollectorCreate) -> CollectorResponse:
        self._require_investor(current_user)
        existing = await self.session.execute(
            select(User).where(User.email == body.email)
        )
        if existing.scalar():
            raise ConflictError("email already in use")
        user = User(
            email=body.email,
            name=body.name,
            phone=body.phone,
            hashed_password=hash_password(body.password),
            role=UserRole.COLLECTOR.value,
            is_active=True,
        )
        self.session.add(user)
        await self.session.flush()
        await self.session.commit()
        await self.session.refresh(user)
        return CollectorResponse.model_validate(user)

    async def deactivate(self, current_user: dict, collector_id: str) -> CollectorResponse:
        self._require_investor(current_user)
        result = await self.session.execute(
            select(User).where(
                User.id == collector_id,
                User.role == UserRole.COLLECTOR.value,
            )
        )
        user = result.scalar()
        if not user:
            from src.core.exceptions.base import NotFoundError
            raise NotFoundError("collector", collector_id)
        user.is_active = False
        await self.session.commit()
        await self.session.refresh(user)
        return CollectorResponse.model_validate(user)
