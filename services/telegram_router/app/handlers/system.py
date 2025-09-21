from __future__ import annotations

from .base import BaseHandler


class SystemHandler(BaseHandler):
    """Handle system level commands such as /help, /cancel, and /exit."""

    async def handle_help(self, *, chat_id: int) -> list[str]:
        existing = self.session_service.get(chat_id) or {}
        if existing.get("sticky"):
            self.clear_session(chat_id)
        return self.render_response("help", {})

    async def handle_cancel(self, *, chat_id: int) -> list[str]:
        self.clear_session(chat_id)
        return self.render_response("canceled", {})

    async def handle_exit(self, *, chat_id: int) -> list[str]:
        self.clear_session(chat_id)
        return self.render_response("canceled", {})

