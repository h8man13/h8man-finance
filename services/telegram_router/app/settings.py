from __future__ import annotations

from functools import lru_cache
from typing import List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )
    # Telegram
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_WEBHOOK_SECRET: str = ""
    TELEGRAM_MODE: str = Field("polling", pattern=r"^(webhook|polling)$")
    REPLY_PARSE_MODE: str = "MarkdownV2"

    # Router
    ROUTER_PORT: int = 8010
    ROUTER_LOG_LEVEL: str = Field("info")
    ROUTER_SESSION_TTL_SEC: int = 300
    ROUTER_OWNER_IDS: str = ""
    IDEMPOTENCY_PATH: str = "/app/data/idempotency.json"
    SESSIONS_DIR: str = "/app/data/sessions"
    REGISTRY_PATH: str = "/config/commands.json"
    COPIES_PATH: str = "/config/router_copies.yaml"
    RANKING_PATH: str = "/config/help_ranking.yaml"
    UI_PATH: str = "/config/ui.yml"

    # Upstreams
    MARKET_DATA_URL: str = "http://market_data:8000"
    PORTFOLIO_CORE_URL: str = "http://portfolio_core:8000"
    FX_URL: str = "http://fx:8000"

    # HTTP client
    HTTP_TIMEOUT_SEC: float = 8.0
    HTTP_RETRIES: int = 2

    @property
    def owner_ids(self) -> List[int]:
        ids = []
        if self.ROUTER_OWNER_IDS:
            for p in self.ROUTER_OWNER_IDS.split(","):
                p = p.strip()
                if p:
                    try:
                        ids.append(int(p))
                    except ValueError:
                        continue
        return ids

    # Note: Do not define an inner `Config` class alongside `model_config` for pydantic v2


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
