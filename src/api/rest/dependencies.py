from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants.enums import UserRole
from src.core.exceptions.base import ForbiddenError, UnauthorizedError
from src.data.clients.postgres_client import AsyncSessionLocal
from src.utils.security import decode_token


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        async with session.begin():
            yield session


async def get_current_user(authorization: str | None = Header(default=None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise UnauthorizedError()
    token = authorization.removeprefix("Bearer ")
    try:
        payload = decode_token(token)
    except ValueError:
        raise UnauthorizedError("invalid or expired token")
    if payload.get("type") != "access":
        raise UnauthorizedError("wrong token type")
    return payload


def require_role(*roles: UserRole):
    async def checker(current_user: dict = Depends(get_current_user)) -> dict:
        if current_user.get("role") not in [r.value for r in roles]:
            raise ForbiddenError()
        return current_user
    return checker
