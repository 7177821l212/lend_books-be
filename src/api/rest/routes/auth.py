from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.middleware.rate_limit import limiter
from src.api.rest.dependencies import get_current_user, get_db
from src.schemas.auth import ChangePasswordRequest, LoginRequest, RefreshRequest, TokenResponse, UserMe

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
async def login(request: Request, body: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
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


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    from src.core.services.auth_service import AuthService
    await AuthService(db).change_password(current_user["sub"], body.current_password, body.new_password)
