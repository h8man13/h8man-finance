import uvicorn
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timezone
import hmac, hashlib, urllib.parse

from .settings import settings
from .api import router as api_router
from .db import open_db, upsert_user

app = FastAPI(title=settings.APP_NAME)

# CORS per spec for Mini App client
if settings.CORS_ALLOW_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(o) for o in settings.CORS_ALLOW_ORIGINS],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

class AuthReq(BaseModel):
    initData: str

@app.post("/auth/telegram")
async def auth_telegram(req: AuthReq):
    # Validate HMAC per Telegram WebApp rules using BOT token
    if not settings.TELEGRAM_BOT_TOKEN:
        return {"ok": False, "error": {"code":"INTERNAL","message":"BOT token missing","source":"market_data","retriable":False}, "ts": datetime.now(timezone.utc).isoformat()}

    parsed = dict(urllib.parse.parse_qsl(req.initData, keep_blank_values=True))
    hash_recv = parsed.pop("hash", None)
    data_check_string = "\n".join([f"{k}={parsed[k]}" for k in sorted(parsed.keys())])
    secret = hashlib.sha256(settings.TELEGRAM_BOT_TOKEN.encode()).digest()
    h = hmac.new(secret, msg=data_check_string.encode(), digestmod=hashlib.sha256).hexdigest()

    if h != hash_recv:
        return {"ok": False, "error": {"code":"BAD_INPUT","message":"invalid initData","source":"market_data","retriable":False}, "ts": datetime.now(timezone.utc).isoformat()}

    # Upsert user
    user = {}
    if "user" in parsed:
        # 'user' is JSON per Telegram
        import json as _json
        u = _json.loads(parsed["user"])
        user = {
            "user_id": u.get("id"),
            "first_name": u.get("first_name"),
            "last_name": u.get("last_name","") or "",
            "username": u.get("username"),
            "language_code": u.get("language_code"),
        }
        conn = await open_db()
        try:
            await upsert_user(conn, user)
        finally:
            await conn.close()

    # Simple sessionless mode per spec option
    return {"ok": True, "data": {"user_id": user.get("user_id")}, "ts": datetime.now(timezone.utc).isoformat()}

# Mount API
app.include_router(api_router)

if __name__ == "__main__":
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=False)
