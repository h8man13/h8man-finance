"""
Settings with Pydantic v2/v1 compatibility and no decorators.

- v2: uses pydantic-settings with model_config
- v1: falls back to pydantic.BaseSettings with inner Config
- Only defines fields referenced by the project files
- All defaults are overrideable via environment or .env
"""

from typing import Optional, List

# Prefer Pydantic v2; fallback to v1
try:
    from pydantic_settings import BaseSettings, SettingsConfigDict  # v2
    V2 = True
except Exception:  # pragma: no cover
    from pydantic import BaseSettings  # v1
    SettingsConfigDict = None  # type: ignore
    V2 = False


class Settings(BaseSettings):
    # App identity & logging
    APP_NAME: str = "market_data"
    ENV: str = "prod"
    LOG_LEVEL: str = "info"

    # Networking (FastAPI/uvicorn)
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Upstream data provider (EODHD)
    # NOTE: API token must be provided in env or .env
    EODHD_API_TOKEN: str
    # Safe default; override with EODHD_BASE_URL in env if needed
    EODHD_BASE_URL: str = "https://eodhd.com/api"

    # FX microservice (docker-compose service name `fx` by default)
    # Override with FX_BASE_URL=http://127.0.0.1:8000 when calling locally from host
    FX_BASE_URL: str = "http://fx:8000"

    # Cache/database
    DB_PATH: str = "/app/data/cache.db"

    # TTLs (seconds)
    QUOTES_TTL_SEC: int = 90
    BENCH_TTL_SEC: int = 900
    META_TTL_SEC: int = 86400

    # Timezone
    TZ: str = "Europe/Berlin"

    # CORS (CSV list, e.g. "https://app.example.com,https://foo.bar")
    CORS_ALLOW_ORIGINS: Optional[str] = None
    CORS_ALLOW_CREDENTIALS: bool = False

    # Config / model_config
    if V2:
        model_config = SettingsConfigDict(
            env_file=".env",
            case_sensitive=True,
            extra="ignore",
        )
    else:
        class Config:  # type: ignore
            env_file = ".env"
            case_sensitive = True
            extra = "ignore"

    # Helper to consume CORS origins as a list in app/main.py
    def cors_origin_list(self) -> Optional[List[str]]:
        if not self.CORS_ALLOW_ORIGINS:
            return None
        return [s.strip() for s in str(self.CORS_ALLOW_ORIGINS).split(",") if s.strip()]


settings = Settings()
