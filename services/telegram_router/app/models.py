from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# Minimal Telegram Update models (enough for text/caption messages)
class TelegramChat(BaseModel):
    id: int


class TelegramUser(BaseModel):
    id: int
    is_bot: Optional[bool] = False
    username: Optional[str] = None


class TelegramMessage(BaseModel):
    message_id: int
    from_: Optional[TelegramUser] = Field(default=None, alias="from")
    chat: TelegramChat
    text: Optional[str] = None
    caption: Optional[str] = None


class TelegramUpdate(BaseModel):
    update_id: int
    message: Optional[TelegramMessage] = None
    edited_message: Optional[TelegramMessage] = None

    def get_message(self) -> Optional[TelegramMessage]:
        return self.message or self.edited_message


class TestRouteIn(BaseModel):
    chat_id: int
    text: str


class ServiceEnvelope(BaseModel):
    ok: bool
    data: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None
    ts: Optional[str] = None


class DispatchRequest(BaseModel):
    service: str
    method: str
    path: str
    payload: Dict[str, Any] = {}

