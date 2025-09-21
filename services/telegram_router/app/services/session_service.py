from __future__ import annotations

import os
from typing import Any, Callable, Dict, List, Optional, Sequence

from ..core.registry import CommandSpec
from ..core.sessions import SessionStore
from ..settings import Settings
from ..ui.loader import load_router_config


class SessionService:
    """Provide higher-level helpers around chat sessions and sticky command rules."""

    def __init__(
        self,
        store: SessionStore,
        settings: Settings,
        config_loader: Callable[[str], Optional[Dict[str, Any]]] = load_router_config,
    ) -> None:
        self._store = store
        self._settings = settings
        self._config_loader = config_loader
        self._sticky_cache: Optional[List[str]] = None
        self._sticky_set: Optional[set[str]] = None

    @property
    def store(self) -> SessionStore:
        return self._store

    def get(self, chat_id: int) -> Optional[Dict[str, Any]]:
        return self._store.get(chat_id)

    def set(self, chat_id: int, data: Dict[str, Any]) -> None:
        self._store.set(chat_id, data)

    def clear(self, chat_id: int) -> None:
        self._store.clear(chat_id)

    def get_sticky_commands(self) -> List[str]:
        if self._sticky_cache is not None:
            return self._sticky_cache
        sticky: List[str] = []
        try:
            config = self._config_loader(self._settings.ROUTER_CONFIG_PATH)
            if not config and self._settings.UI_PATH:
                alt_path = os.path.join(
                    os.path.dirname(self._settings.UI_PATH), "router_config.yaml"
                )
                if os.path.exists(alt_path):
                    config = self._config_loader(alt_path)
            if config:
                session_config = (config.get("session") or {})
                raw = session_config.get("sticky_commands", [])
                if isinstance(raw, list):
                    sticky = [str(cmd) for cmd in raw]
        except Exception:
            sticky = []
        self._sticky_cache = sticky
        self._sticky_set = set(sticky)
        return sticky

    def is_sticky(self, command_name: Optional[str]) -> bool:
        if not command_name:
            return False
        if self._sticky_cache is None:
            self.get_sticky_commands()
        return command_name in (self._sticky_set or set())

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
        session: Dict[str, Any] = {
            "chat_id": chat_id,
            "cmd": spec.name,
            "expected": self._expected_fields(spec),
            "got": dict(values or {}),
            "missing_from": list(missing or []),
            "sticky": self._resolve_sticky(spec, sticky),
        }
        if extra:
            session.update(extra)
        self._store.set(chat_id, session)
        return session

    def create_sticky_session(
        self,
        chat_id: int,
        spec: CommandSpec,
        values: Optional[Dict[str, Any]] = None,
        missing: Sequence[str] | None = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return self.create_session(
            chat_id,
            spec,
            values=values,
            missing=missing,
            sticky=True,
            extra=extra,
        )

    def should_clear_session(
        self,
        spec: Optional[CommandSpec],
        existing_session: Optional[Dict[str, Any]],
    ) -> bool:
        if not spec or not existing_session:
            return False
        if not existing_session.get("sticky"):
            return False
        return existing_session.get("cmd") != spec.name

    def _resolve_sticky(self, spec: CommandSpec, sticky: Optional[bool]) -> bool:
        if sticky is not None:
            return bool(sticky)
        return self.is_sticky(spec.name)

    @staticmethod
    def _expected_fields(spec: CommandSpec) -> List[str]:
        fields: List[str] = []
        for field in spec.args_schema:
            if isinstance(field, dict):
                name = field.get("name")
                if isinstance(name, str):
                    fields.append(name)
        return fields

