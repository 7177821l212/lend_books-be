"""Collector service — list and create collectors."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants.enums import UserRole
from src.core.exceptions.base import ConflictError, ForbiddenError
from src.data.models.postgres.user import User
from src.schemas.collector import CollectorCreate, CollectorResponse, CollectorUpdate
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
            .where(User.role == UserRole.COLLECTOR.value)
            .order_by(User.is_active.desc(), User.name)
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
        await self.session.refresh(user)
        return CollectorResponse.model_validate(user)

    async def get(self, current_user: dict, collector_id: str) -> CollectorResponse:
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
        return CollectorResponse.model_validate(user)

    async def update(
        self, current_user: dict, collector_id: str, body: CollectorUpdate
    ) -> CollectorResponse:
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
        if body.name is not None:
            user.name = body.name
        if body.phone is not None:
            user.phone = body.phone
        if body.photo_url is not None:
            user.photo_url = body.photo_url
        await self.session.flush()
        await self.session.refresh(user)
        return CollectorResponse.model_validate(user)

    async def activate(self, current_user: dict, collector_id: str) -> CollectorResponse:
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
        user.is_active = True
        await self.session.flush()
        await self.session.refresh(user)
        return CollectorResponse.model_validate(user)

    async def delete(self, current_user: dict, collector_id: str) -> None:
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
        from src.data.models.postgres.loan import Loan
        from src.constants.enums import LoanStatus
        from sqlalchemy import func
        active_count = (await self.session.execute(
            select(func.count(Loan.id)).where(
                Loan.collector_id == collector_id,
                Loan.status == LoanStatus.ACTIVE.value,
            )
        )).scalar_one()
        if int(active_count) > 0:
            from src.core.exceptions.base import ConflictError
            raise ConflictError("reassign or close active loans before deleting this collector")
        user.is_active = False
        await self.session.flush()

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
        await self.session.flush()
        await self.session.refresh(user)
        return CollectorResponse.model_validate(user)
