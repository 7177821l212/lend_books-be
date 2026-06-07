from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from src.data.clients.postgres_client import engine

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> JSONResponse:
    db_status = "ok"
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        db_status = "error"

    http_status = 200 if db_status == "ok" else 503
    return JSONResponse(
        status_code=http_status,
        content={"status": "ok", "db": db_status},
    )
