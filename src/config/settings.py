from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_ENV: str = "development"
    APP_NAME: str = "lendbook-be"
    LOG_LEVEL: str = "INFO"
    BUSINESS_TIMEZONE: str = "Asia/Kolkata"

    DATABASE_URL: str = ""
    DATABASE_POOL_SIZE: int = 5
    DATABASE_MAX_OVERFLOW: int = 10
    DATABASE_POOL_RECYCLE: int = 1800

    JWT_SECRET_KEY: str = Field(
        default="",
        validation_alias=AliasChoices("JWT_SECRET_KEY", "JWT_SECRET"),
    )
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    CORS_ORIGINS: list[str] = ["http://localhost:8081"]

    GCS_BUCKET_NAME: str = Field(
        default="",
        validation_alias=AliasChoices("GCS_BUCKET_NAME", "GCS_BUCKET"),
    )
    GOOGLE_APPLICATION_CREDENTIALS: str = ""

    @model_validator(mode="after")
    def require_production_configuration(self) -> "Settings":
        if self.APP_ENV.lower() != "production":
            return self

        missing = [
            name
            for name, value in (
                ("DATABASE_URL", self.DATABASE_URL),
                ("JWT_SECRET_KEY", self.JWT_SECRET_KEY),
                ("GCS_BUCKET_NAME", self.GCS_BUCKET_NAME),
            )
            if not value.strip()
        ]
        if missing:
            raise ValueError(
                "Missing required production configuration: " + ", ".join(missing)
            )
        if self.JWT_SECRET_KEY.strip().lower() in {"dummy", "change-me"}:
            raise ValueError("JWT_SECRET_KEY must be a real production secret")
        return self


settings = Settings()
