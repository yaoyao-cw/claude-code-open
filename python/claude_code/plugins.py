from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _state_dir() -> Path:
    directory = Path.home() / ".claude"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _plugins_path() -> Path:
    return _state_dir() / "plugins.json"


@dataclass
class PluginState:
    name: str
    version: str
    path: str
    enabled: bool = True
    loaded: bool = False
    description: str | None = None


class PluginManager:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or _plugins_path()

    def _load(self) -> dict[str, Any]:
        if self.path.exists():
            try:
                return json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return {"plugins": []}
        return {"plugins": []}

    def _save(self, data: dict[str, Any]) -> None:
        self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    def list_plugins(self) -> list[PluginState]:
        data = self._load()
        return [self._deserialize(p) for p in data.get("plugins", [])]

    def install(self, plugin_path: str) -> PluginState:
        name = Path(plugin_path).stem
        state = PluginState(name=name, version="0.1.0", path=plugin_path, enabled=True, loaded=True)
        data = self._load()
        data.setdefault("plugins", [])
        data["plugins"] = [p for p in data["plugins"] if p.get("name") != name]
        data["plugins"].append(self._serialize(state))
        self._save(data)
        return state

    def remove(self, plugin_name: str) -> bool:
        data = self._load()
        plugins = data.get("plugins", [])
        filtered = [p for p in plugins if p.get("name") != plugin_name]
        if len(filtered) == len(plugins):
            return False
        data["plugins"] = filtered
        self._save(data)
        return True

    def enable(self, plugin_name: str) -> bool:
        return self._set_enabled(plugin_name, True)

    def disable(self, plugin_name: str) -> bool:
        return self._set_enabled(plugin_name, False)

    def _set_enabled(self, plugin_name: str, enabled: bool) -> bool:
        data = self._load()
        for plugin in data.get("plugins", []):
            if plugin.get("name") == plugin_name:
                plugin["enabled"] = enabled
                self._save(data)
                return True
        return False

    @staticmethod
    def _serialize(state: PluginState) -> dict[str, Any]:
        return {
            "name": state.name,
            "version": state.version,
            "path": state.path,
            "enabled": state.enabled,
            "loaded": state.loaded,
            "description": state.description,
        }

    @staticmethod
    def _deserialize(data: dict[str, Any]) -> PluginState:
        return PluginState(
            name=data.get("name", "unknown"),
            version=data.get("version", "0.0.0"),
            path=data.get("path", ""),
            enabled=bool(data.get("enabled", True)),
            loaded=bool(data.get("loaded", False)),
            description=data.get("description"),
        )


plugin_manager = PluginManager()
