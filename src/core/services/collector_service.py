"""Collector service — list active collectors for assignment."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants.enums import UserRole
from src.core.exceptions.base import ForbiddenError
from src.data.models.postgres.user import User
from src.schemas.collector import CollectorResponse


class CollectorService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(self, current_user: dict) -> list[CollectorResponse]:
        if current_user.get("role") != UserRole.INVESTOR.value:
            raise ForbiddenError("only investor can list collectors")
        result = await self.session.execute(
            select(User)
            .where(User.role == UserRole.COLLECTOR.value)
            .order_by(User.name)
        )
        return [CollectorResponse.model_validate(u) for u in result.scalars()]
