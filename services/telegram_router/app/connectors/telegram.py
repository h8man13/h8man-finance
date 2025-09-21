from __future__ import annotations

import asyncio
from typing import Any, Dict, Callable, Awaitable

import httpx

from ..models import TelegramUpdate


class TelegramConnector:
    def __init__(self, token: str, process_update_func: Callable[[TelegramUpdate], Awaitable[None]]):
        self.token = token
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.process_update = process_update_func
        self._offset: int | None = None
        self._running = False

    async def start_polling(self):
        """Start polling for Telegram updates."""
        self._running = True
        async with httpx.AsyncClient(timeout=30.0) as client:
            while self._running:
                try:
                    params = {"timeout": 25}
                    if self._offset is not None:
                        params["offset"] = self._offset

                    response = await client.get(f"{self.base_url}/getUpdates", params=params)
                    data = response.json()

                    if not data.get("ok"):
                        await asyncio.sleep(1.0)
                        continue

                    for update_data in data.get("result", []):
                        update = TelegramUpdate.model_validate(update_data)
                        await self.process_update(update)
                        self._offset = update.update_id + 1

                except Exception as e:
                    # Log error using the same logging pattern as the original
                    import json
                    print(json.dumps({"action": "poll", "status": "error", "error": str(e)}, ensure_ascii=False))
                    await asyncio.sleep(1.0)

    def stop_polling(self):
        """Stop the polling loop."""
        self._running = False

    async def send_message(self, chat_id: int, text: str, parse_mode: str = "MarkdownV2") -> bool:
        """Send a message to a chat."""
        url = f"{self.base_url}/sendMessage"
        async with httpx.AsyncClient(timeout=8.0) as client:
            payload = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
            }
            try:
                response = await client.post(url, json=payload)
                return response.status_code == 200
            except Exception:
                return False