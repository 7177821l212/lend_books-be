"""Repository for the refresh-token revocation list."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.data.models.postgres.revoked_token import RevokedToken


class RevokedTokenRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def is_revoked(self, jti: str) -> bool:
        result = await self.session.execute(select(RevokedToken.jti).where(RevokedToken.jti == jti))
        return result.scalar_one_or_none() is not None

    async def revoke(self, jti: str, user_id: str) -> None:
        """Insert a revocation. Silently no-ops on PK collision (already revoked)."""
        try:
            self.session.add(RevokedToken(jti=jti, user_id=user_id))
            await self.session.flush()
        except IntegrityError:
            await self.session.rollback()
