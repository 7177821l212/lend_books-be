from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_ENV: str = "development"
    APP_NAME: str = "lendbook-be"
    LOG_LEVEL: str = "INFO"

    DATABASE_URL: str = ""
    DATABASE_POOL_SIZE: int = 5
    DATABASE_MAX_OVERFLOW: int = 10
    DATABASE_POOL_RECYCLE: int = 1800

    JWT_SECRET_KEY: str = ""
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    CORS_ORIGINS: list[str] = ["http://localhost:8081"]

    GCS_BUCKET_NAME: str = ""
    GOOGLE_APPLICATION_CREDENTIALS: str = ""

    # Local-filesystem storage fallback — used automatically when GCS credentials
    # are unavailable (e.g. local Docker dev). Files are written under
    # LOCAL_UPLOAD_DIR and served publicly from `{PUBLIC_BASE_URL}/files/...`.
    # Relative default so it works both on the host (pytest) and in-container;
    # docker-compose overrides it to an absolute, volume-backed path.
    LOCAL_UPLOAD_DIR: str = "./uploads"
    PUBLIC_BASE_URL: str = "http://localhost:8000"


settings = Settings()
