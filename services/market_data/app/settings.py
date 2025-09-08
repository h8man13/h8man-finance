from pydantic import BaseSettings, AnyHttpUrl, validator
from typing import List, Optional
from decimal import Decimal

class Settings(BaseSettings):
    APP_NAME: str = "market_data"
    ENV: str = "prod"
    LOG_LEVEL: str = "info"

    # Networking
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    CORS_ALLOW_ORIGINS: List[AnyHttpUrl] = []

    # Upstream services
    EODHD_BASE_URL: str = "https://eodhd.com/api"
    EODHD_API_TOKEN: str
    FX_BASE_URL: str = "http://fx:8000"

    # Cache and DB
    DB_PATH: str = "/app/data/cache.db"
    QUOTES_TTL_SEC: int = 90
    BENCH_TTL_SEC: int = 900
    META_TTL_SEC: int = 86400

    # Auth
    TELEGRAM_BOT_TOKEN: Optional[str] = None

    # Timezone
    TZ: str = "Europe/Berlin"

    class Config:
        env_file = ".env"
        case_sensitive = True

    @validator("QUOTES_TTL_SEC", "BENCH_TTL_SEC", "META_TTL_SEC")
    def ttl_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("TTL must be positive")
        return v

settings = Settings()  # type: ignore
