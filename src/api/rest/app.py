import logging
import logging.config

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from src.api.middleware.logging import RequestLoggingMiddleware
from src.api.middleware.rate_limit import limiter
from src.api.middleware.request_id import RequestIDMiddleware
from src.api.rest.routes import (
    auth,
    collectors,
    customers,
    health,
    loans,
    payments,
    reports,
    uploads,
)
from src.config.settings import settings

_LOG_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "format": '{"time":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","msg":"%(message)s"}',
            "datefmt": "%Y-%m-%dT%H:%M:%S",
        },
        "plain": {
            "format": "%(asctime)s %(levelname)-8s %(name)s  %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json" if settings.APP_ENV == "production" else "plain",
        }
    },
    "root": {"handlers": ["console"], "level": settings.LOG_LEVEL},
    "loggers": {
        "uvicorn.access": {"handlers": [], "propagate": False},
    },
}


def create_app() -> FastAPI:
    logging.config.dictConfig(_LOG_CONFIG)

    app = FastAPI(
        title="LendBook API",
        version="0.1.0",
        docs_url="/docs" if settings.APP_ENV != "production" else None,
        redoc_url=None,
    )

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # Middleware applied last-in first-out; RequestID must run before Logging
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(RequestIDMiddleware)
    app.add_middleware(SlowAPIMiddleware)
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
    app.include_router(uploads.router, prefix="/api/v1")

    return app
