from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.rest.routes import auth, collectors, customers, health, loans, payments, reports
from src.config.settings import settings


def create_app() -> FastAPI:
    app = FastAPI(
        title="LendBook API",
        version="0.1.0",
        docs_url="/docs" if settings.APP_ENV != "production" else None,
        redoc_url=None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(customers.router, prefix="/api/v1")
    app.include_router(loans.router, prefix="/api/v1")
    app.include_router(payments.router, prefix="/api/v1")
    app.include_router(collectors.router, prefix="/api/v1")
    app.include_router(reports.router, prefix="/api/v1")

    return app
