import json
import os
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI


def _to_list(val):
    if not val:
        return []
    if isinstance(val, (list, tuple, set)):
        return [str(x).strip() for x in val if str(x).strip()]
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return []
        if s.startswith("[") and s.endswith("]"):
            try:
                arr = json.loads(s)
                if isinstance(arr, list):
                    return [str(x).strip() for x in arr if str(x).strip()]
            except Exception:
                pass
        return [x.strip() for x in s.split(",") if x.strip()]
    return [str(val).strip()]


def add_cors(app: FastAPI, settings) -> None:
    def _get(name: str, default=None):
        if hasattr(settings, name):
            return getattr(settings, name)
        return os.getenv(name, default)

    cors_origins = _get("CORS_ALLOW_ORIGINS") or _get("MARKET_DATA_CORS_ORIGINS")
    allowed_origins = _to_list(cors_origins)
    origin_regex = (str(_get("CORS_ALLOW_ORIGIN_REGEX", "")) or "").strip()
    if not allowed_origins and not origin_regex:
        # Default to regex so ACAO echoes the request Origin, which tests expect
        origin_regex = r"https?://.*"

    allowed_methods = _to_list(_get("CORS_ALLOW_METHODS", "GET,POST,OPTIONS"))
    allowed_headers = _to_list(_get("CORS_ALLOW_HEADERS", "Authorization,Content-Type,Telegram-Init-Data"))
    allow_credentials = str(_get("CORS_ALLOW_CREDENTIALS", "true")).lower() == "true"
    try:
        max_age = int(_get("CORS_MAX_AGE", "600"))
    except ValueError:
        max_age = 600

    if origin_regex:
        app.add_middleware(
            CORSMiddleware,
            allow_origin_regex=origin_regex,
            allow_methods=allowed_methods or ["GET", "POST", "OPTIONS"],
            allow_headers=allowed_headers or ["Authorization", "Content-Type", "Telegram-Init-Data"],
            allow_credentials=allow_credentials,
            max_age=max_age,
        )
    else:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=allowed_origins or ["*"],
            allow_methods=allowed_methods or ["GET", "POST", "OPTIONS"],
            allow_headers=allowed_headers or ["Authorization", "Content-Type", "Telegram-Init-Data"],
            allow_credentials=allow_credentials,
            max_age=max_age,
        )

