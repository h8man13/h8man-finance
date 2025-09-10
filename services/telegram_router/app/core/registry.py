from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class CommandSpec:
    name: str
    aliases: List[str]
    description: str
    args_schema: List[Dict[str, Any]]
    dispatch: Dict[str, Any]
    help: Dict[str, Any]


class Registry:
    def __init__(self, path: str):
        self.path = path
        self._mtime = 0.0
        self._by_name: Dict[str, CommandSpec] = {}
        self._aliases: Dict[str, str] = {}

    def _load(self):
        with open(self.path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        by_name: Dict[str, CommandSpec] = {}
        aliases: Dict[str, str] = {}
        for c in raw.get("commands", []):
            spec = CommandSpec(
                name=c["name"],
                aliases=c.get("aliases", []),
                description=c.get("description", ""),
                args_schema=c.get("args_schema", []),
                dispatch=c.get("dispatch", {}),
                help=c.get("help", {}),
            )
            by_name[spec.name] = spec
            for a in spec.aliases:
                aliases[a] = spec.name
        self._by_name = by_name
        self._aliases = aliases

    def _maybe_reload(self):
        try:
            mtime = os.path.getmtime(self.path)
        except FileNotFoundError:
            return
        if mtime > self._mtime:
            self._load()
            self._mtime = mtime

    def get(self, cmd: str) -> Optional[CommandSpec]:
        self._maybe_reload()
        # alias resolution to canonical
        key = cmd
        if cmd in self._aliases:
            key = self._aliases[cmd]
        return self._by_name.get(key)

    def all(self) -> List[CommandSpec]:
        self._maybe_reload()
        return list(self._by_name.values())

