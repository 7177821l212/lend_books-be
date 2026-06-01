from typing import Any, Generic, TypeVar

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.models.postgres.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    def __init__(self, model: type[ModelT], session: AsyncSession) -> None:
        self.model = model
        self.session = session

    async def get_by_id(self, id: str) -> ModelT | None:
        return await self.session.get(self.model, id)

    async def list(
        self,
        filters: list[Any] | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[ModelT], int]:
        query = select(self.model)
        count_query = select(func.count()).select_from(self.model)
        if filters:
            query = query.where(*filters)
            count_query = count_query.where(*filters)
        total = (await self.session.execute(count_query)).scalar_one()
        rows = (await self.session.execute(query.offset(offset).limit(limit))).scalars().all()
        return list(rows), total

    async def create(self, obj: ModelT) -> ModelT:
        self.session.add(obj)
        await self.session.flush()
        await self.session.refresh(obj)
        return obj

    async def delete(self, obj: ModelT) -> None:
        await self.session.delete(obj)
        await self.session.flush()
