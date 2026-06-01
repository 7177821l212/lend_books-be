from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.rest.dependencies import get_current_user, get_db
from src.schemas.auth import LoginRequest, RefreshRequest, TokenResponse, UserMe

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    from src.core.services.auth_service import AuthService
    return await AuthService(db).login(body.email, body.password)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    from src.core.services.auth_service import AuthService
    return await AuthService(db).refresh(body.refresh_token)


@router.get("/me", response_model=UserMe)
async def me(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserMe:
    from src.core.services.auth_service import AuthService
    return await AuthService(db).get_me(current_user["sub"])
