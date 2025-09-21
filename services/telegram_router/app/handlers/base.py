from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Sequence

from ..core.dispatcher import Dispatcher
from ..core.registry import CommandSpec
from ..services import FormattingService, SessionService
from ..settings import Settings
from ..ui.loader import render_screen


class BaseHandler:
    def __init__(
        self,
        ui: Dict[str, Any],
        session_service: SessionService,
        dispatcher: Dispatcher,
        settings: Settings,
        *,
        sticky_commands: Iterable[str] | None = None,
        formatting_service: FormattingService | None = None,
    ) -> None:
        self.ui = ui
        self.session_service = session_service
        self.dispatcher = dispatcher
        self.settings = settings
        self.formatting = formatting_service
        base_sticky = session_service.get_sticky_commands()
        self._sticky_commands = set(sticky_commands or base_sticky)

    def create_session(
        self,
        chat_id: int,
        spec: CommandSpec,
        values: Optional[Dict[str, Any]] = None,
        missing: Sequence[str] | None = None,
        *,
        sticky: Optional[bool] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        resolved_sticky = self._resolve_sticky(spec, sticky)
        return self.session_service.create_session(
            chat_id,
            spec,
            values=values,
            missing=missing,
            sticky=resolved_sticky,
            extra=extra,
        )

    def render_response(self, screen_key: str, data: Dict[str, Any]) -> list[str]:
        pages = render_screen(self.ui, screen_key, data)
        return [p for p in pages] if pages else []

    def clear_session(self, chat_id: int) -> None:
        self.session_service.clear(chat_id)

    def is_sticky(self, spec: CommandSpec) -> bool:
        return self.session_service.is_sticky(spec.name)

    def ttl_minutes(self) -> int:
        return int(self.settings.ROUTER_SESSION_TTL_SEC // 60)

    def _resolve_sticky(self, spec: CommandSpec, sticky: Optional[bool]) -> bool:
        if sticky is not None:
            return bool(sticky)
        if spec.name in self._sticky_commands:
            return True
        return self.session_service.is_sticky(spec.name)

