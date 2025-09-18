"""Application settings for portfolio_core."""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    APP_NAME: str = "portfolio_core"
    LOG_LEVEL: str = "INFO"

    HOST: str = "0.0.0.0"
    PORT: int = 8000

    DB_PATH: str = "/app/data/portfolio.db"

    MARKET_DATA_BASE_URL: str = "http://market_data:8000"
    MARKET_DATA_TIMEOUT_SEC: float = 5.0
    MARKET_DATA_RETRIES: int = 2
    QUOTES_CACHE_TTL_SEC: int = 90
    META_CACHE_TTL_SEC: int = 86400
    BENCHMARK_CACHE_TTL_SEC: int = 900

    DEFAULT_STOCK_TARGET_PCT: int = 60
    DEFAULT_ETF_TARGET_PCT: int = 30
    DEFAULT_CRYPTO_TARGET_PCT: int = 10

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    def validate_targets(self) -> None:
        total = self.DEFAULT_STOCK_TARGET_PCT + self.DEFAULT_ETF_TARGET_PCT + self.DEFAULT_CRYPTO_TARGET_PCT
        if total != 100:
            raise ValueError("Default allocation targets must sum to 100")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.validate_targets()
    return settings


settings = get_settings()

