"""
Settings with Pydantic v2 compatibility and environment configuration.
"""
from typing import Optional, List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # App identity & logging
    APP_NAME: str = "portfolio_core"
    ENV: str = "prod"
    LOG_LEVEL: str = "info"

    # Networking (FastAPI/uvicorn)
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # External services
    MARKET_DATA_URL: str = "http://market_data:8000"
    FX_URL: str = "http://fx:8000"

    # Database
    DB_PATH: str = "/app/data/portfolio.db"

    # Telegram
    TELEGRAM_BOT_TOKEN: str = ""
    INITDATA_MAX_AGE_SEC: int = 3600

    # CORS (CSV list for the Mini App)
    CORS_ALLOW_ORIGINS: Optional[str] = None
    CORS_ALLOW_CREDENTIALS: bool = False
    
    # Timezone (for all date/time calculations)
    TZ: str = "Europe/Berlin"
    
    # Target allocation defaults
    DEFAULT_ETF_TARGET: int = 60
    DEFAULT_STOCK_TARGET: int = 30
    DEFAULT_CRYPTO_TARGET: int = 10

    # Model configuration
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore",
    )

    # Helper to consume CORS origins as a list
    def cors_origin_list(self) -> Optional[List[str]]:
        if not self.CORS_ALLOW_ORIGINS:
            return None
        return [s.strip() for s in str(self.CORS_ALLOW_ORIGINS).split(",") if s.strip()]


def get_settings(test_db_path: Optional[str] = None) -> Settings:
    config = Settings()
    if test_db_path:
        config.DB_PATH = test_db_path
    return config


settings = get_settings()