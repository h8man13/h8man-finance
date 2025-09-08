"""
Settings with Pydantic v1/v2 compatibility.

- Uses pydantic-settings on v2.
- Ignores unknown env keys.
- Keeps your defaults (QUOTES/BENCH/META TTLs, PORT, LOG_LEVEL).
"""

from typing import Optional

# Prefer Pydantic v2; fallback to v1 for older envs
try:
    from pydantic_settings import BaseSettings  # v2
    from pydantic import field_validator        # v2
    V2 = True
except Exception:  # pragma: no cover
    from pydantic import BaseSettings, validator  # v1
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

        @field_validator("CORS_ALLOW_ORIGINS", mode="before")
        def _normalize_cors(cls, v):
            if not v:
                return None
            return ",".join(s.strip() for s in str(v).split(",") if s.strip())
    else:
        class Config:  # pydantic v1
            extra = "ignore"

        @validator("CORS_ALLOW_ORIGINS", pre=True)
        def _normalize_cors(cls, v):
            if not v:
                return None
            return ",".join(s.strip() for s in str(v).split(",") if s.strip())


settings = Settings()
