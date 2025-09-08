"""
Settings with Pydantic v1/v2 compatibility.

- Uses pydantic-settings on v2.
- Ignores unknown env keys.
- Keeps your defaults from the spec.
"""

from typing import Optional

# Prefer Pydantic v2; fallback to v1 for older envs
try:
    from pydantic_settings import BaseSettings  # v2
    from pydantic import field_validator as validator  # v2 alias
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

    # Optional CORS
    CORS_ALLOW_ORIGINS: Optional[str] = None  # CSV list
    CORS_ALLOW_CREDENTIALS: bool = False

    if V2:
        model_config = {"extra": "ignore"}  # v2
    else:
        class Config:  # v1
            extra = "ignore"

    @validator("CORS_ALLOW_ORIGINS", pre=True)
    def _normalize_cors(cls, v):
        if not v:
            return None
        return ",".join(s.strip() for s in str(v).split(",") if s.strip())


settings = Settings()
