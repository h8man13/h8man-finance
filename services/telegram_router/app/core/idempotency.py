from __future__ import annotations

import json
import os
import time
from typing import Dict


class IdempotencyStore:
    def __init__(self, path: str, max_per_chat: int = 50):
        self.path = path
        self.max_per_chat = max_per_chat
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        if not os.path.exists(self.path):
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump({"chats": {}}, f)

    def _load(self) -> Dict:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"chats": {}}

    def _save(self, data: Dict) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f)

    def seen(self, chat_id: int, update_id: int) -> bool:
        data = self._load()
        chats = data.setdefault("chats", {})
        arr = chats.setdefault(str(chat_id), [])
        if update_id in arr:
            return True
        arr.append(update_id)
        if len(arr) > self.max_per_chat:
            del arr[:-self.max_per_chat]
        self._save(data)
        return False

