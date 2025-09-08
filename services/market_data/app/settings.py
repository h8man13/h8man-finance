"""
Settings with Pydantic v1/v2 compatibility (no validators needed).

- Works with pydantic v2 (via pydantic-settings) and v1 fallback.
- Ignores unknown env keys.
- Keeps your defaults (QUOTES/BENCH/META TTLs, PORT, LOG_LEVEL).
"""

from typing import Optional, List

# Prefer Pydantic v2; fallback to v1 for older envs
try:
    from pydantic_settings import BaseSettings  # v2
    V2 = True
except Exception:  # pragma: no cover
    from pydantic import BaseSettings  # v1
    V2 = False


class Settings(BaseSettings):
    # Upstream
    EODHD_API_TOKEN: str

    # TTLs (seconds)
    QUOTES_TTL_SEC: int = 90
    BENCH_TTL_SEC: int = 900
    META_TTL_SEC: int = 86400

    # Service
    PORT: int = 8000
    LOG_LEVEL: str = "INFO"

    # Optional CORS (CSV list, e.g. "https://app.example.com,https://foo.bar")
    CORS_ALLOW_ORIGINS: Optional[str] = None
    CORS_ALLOW_CREDENTIALS: bool = False

    # Extra settings: ignore unknown env keys
    if V2:
        model_config = {"extra": "ignore"}  # pydantic v2
    else:
        class Config:  # pydantic v1
            extra = "ignore"

    # Helper for code that needs a list
    def cors_origin_list(self) -> Optional[List[str]]:
        if not self.CORS_ALLOW_ORIGINS:
            return None
        return [s.strip() for s in str(self.CORS_ALLOW_ORIGINS).split(",") if s.strip()]


settings = Settings()
