from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Optional


class SessionStore:
    def __init__(self, dir_path: str, ttl_sec: int = 300):
        self.dir_path = dir_path
        self.ttl_sec = ttl_sec
        os.makedirs(self.dir_path, exist_ok=True)

    def _path(self, chat_id: int) -> str:
        return os.path.join(self.dir_path, f"{chat_id}.json")

    def get(self, chat_id: int) -> Optional[Dict[str, Any]]:
        path = self._path(chat_id)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return None
        ts = data.get("ts", 0)
        ttl = int(data.get("ttl_sec", self.ttl_sec))
        if time.time() - ts > ttl:
            try:
                os.remove(path)
            except OSError:
                pass
            return None
        return data

    def set(self, chat_id: int, data: Dict[str, Any]) -> None:
        path = self._path(chat_id)
        data = dict(data)
        data["ts"] = int(time.time())
        data["ttl_sec"] = int(self.ttl_sec)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

    def clear(self, chat_id: int) -> None:
        path = self._path(chat_id)
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass

