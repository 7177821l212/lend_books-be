"""Authentication service — login, refresh (with revocation), get_me."""

from sqlalchemy.ext.asyncio import AsyncSession

from src.core.exceptions.base import UnauthorizedError
from src.data.repositories.revoked_token_repository import RevokedTokenRepository
from src.data.repositories.user_repository import UserRepository
from src.schemas.auth import TokenResponse, UserMe
from src.utils.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.users = UserRepository(session)
        self.revoked = RevokedTokenRepository(session)

    async def login(self, email: str, password: str) -> TokenResponse:
        user = await self.users.get_by_email(email.lower().strip())
        if user is None or not user.is_active:
            raise UnauthorizedError("invalid credentials")
        if not verify_password(password, user.hashed_password):
            raise UnauthorizedError("invalid credentials")

        access = create_access_token(subject=user.id, role=user.role)
        refresh = create_refresh_token(subject=user.id)
        return TokenResponse(access_token=access, refresh_token=refresh)

    async def refresh(self, refresh_token: str) -> TokenResponse:
        try:
            payload = decode_token(refresh_token)
        except ValueError as exc:
            raise UnauthorizedError("invalid or expired refresh token") from exc
        if payload.get("type") != "refresh":
            raise UnauthorizedError("wrong token type")

        jti = payload.get("jti")
        user_id = payload.get("sub")
        if not jti or not user_id:
            raise UnauthorizedError("invalid token payload")

        # Replay protection — reject a refresh token whose jti is already revoked
        if await self.revoked.is_revoked(jti):
            raise UnauthorizedError("refresh token has been revoked")

        user = await self.users.get_by_id(user_id)
        if user is None or not user.is_active:
            raise UnauthorizedError("user not found")

        # Rotate: revoke the incoming refresh token, then issue a new pair
        await self.revoked.revoke(jti=jti, user_id=user.id)

        access = create_access_token(subject=user.id, role=user.role)
        rotated = create_refresh_token(subject=user.id)
        return TokenResponse(access_token=access, refresh_token=rotated)

    async def get_me(self, user_id: str) -> UserMe:
        user = await self.users.get_by_id(user_id)
        if user is None:
            raise UnauthorizedError("user not found")
        return UserMe.model_validate(user)
