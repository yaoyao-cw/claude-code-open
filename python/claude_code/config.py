from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _state_dir() -> Path:
    directory = Path.home() / ".claude"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _settings_path() -> Path:
    return _state_dir() / "settings.json"


@dataclass
class ConfigManager:
    settings_path: Path = field(default_factory=_settings_path)
    _cache: dict[str, Any] | None = None

    def _load(self) -> dict[str, Any]:
        if self._cache is not None:
            return self._cache
        if self.settings_path.exists():
            try:
                self._cache = json.loads(self.settings_path.read_text(encoding="utf-8"))
                return self._cache
            except json.JSONDecodeError:
                self._cache = {}
                return self._cache
        self._cache = {}
        return self._cache

    def _save(self) -> None:
        data = self._load()
        self.settings_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def get(self, key: str, default: Any | None = None) -> Any:
        return self._load().get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._load()[key] = value
        self._save()

    def get_mcp_servers(self) -> dict[str, Any]:
        return self._load().get("mcpServers", {})

    def add_mcp_server(self, name: str, config: dict[str, Any]) -> None:
        servers = self._load().setdefault("mcpServers", {})
        servers[name] = config
        self._save()

    def remove_mcp_server(self, name: str) -> bool:
        servers = self._load().get("mcpServers", {})
        if name in servers:
            del servers[name]
            self._save()
            return True
        return False


config_manager = ConfigManager()
