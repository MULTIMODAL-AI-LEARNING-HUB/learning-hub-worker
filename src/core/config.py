"""Worker settings."""

from typing import Any
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_learning_hub"
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"

    MINIO_ENDPOINT: str = "localhost:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin123"
    MINIO_BUCKET_NAME: str = "documents-bucket"
    MINIO_SECURE: bool = False

    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6333
    QDRANT_URL: str | None = None
    QDRANT_API_KEY: str | None = None

    AI_SERVICE_URL: str = "http://localhost:8001"
    INTERNAL_API_KEY: str = ""
    DEBUG: bool = False

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def assemble_db_url(cls, v: Any) -> str:
        if isinstance(v, str):
            if v.startswith("postgres://"):
                v = v.replace("postgres://", "postgresql://", 1)
            if v.startswith("postgresql://") and not v.startswith("postgresql+asyncpg://"):
                v = v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    @model_validator(mode="after")
    def validate_secrets(self) -> "Settings":
        import sys
        is_test = "pytest" in sys.modules
        if is_test:
            return self

        weak_values = {"", "secret", "changeme", "your_internal_api_key", "your_internal_key"}
        if not self.DEBUG:
            if not self.INTERNAL_API_KEY or self.INTERNAL_API_KEY.lower() in weak_values or len(self.INTERNAL_API_KEY) < 16:
                raise ValueError(
                    "INTERNAL_API_KEY must be a secure, non-default string in production. "
                    "Generate one with: python -c \"import secrets; print(secrets.token_hex(16))\""
                )
            if not self.MINIO_ACCESS_KEY or self.MINIO_ACCESS_KEY == "minioadmin":
                raise ValueError("MINIO_ACCESS_KEY must not be the default value in production")
            if not self.MINIO_SECRET_KEY or self.MINIO_SECRET_KEY == "minioadmin123":
                raise ValueError(
                    "MINIO_SECRET_KEY must not be the default value in production. "
                    "Set a strong secret key in your .env file."
                )
            if not self.MINIO_SECURE:
                raise ValueError("MINIO_SECURE must be true in production")
        return self


settings = Settings()
