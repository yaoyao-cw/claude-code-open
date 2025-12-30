"""Plugin system for the Python Claude Code surface."""
from __future__ import annotations

import importlib
import pathlib
import sys
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any, Callable, Dict, Iterable, List, Optional

from .errors import PluginError
from .types import ToolDefinition, ToolResult


@dataclass
class PluginMetadata:
    name: str
    version: str
    description: Optional[str] = None
    author: Optional[str] = None
    homepage: Optional[str] = None
    license: Optional[str] = None
    dependencies: Dict[str, str] = field(default_factory=dict)


class Plugin:
    metadata: PluginMetadata
    tools: List[ToolDefinition] = []

    def init(self, context: "PluginContext") -> None:  # pragma: no cover - default no-op
        return None

    def activate(self, context: "PluginContext") -> None:  # pragma: no cover - default no-op
        return None

    def deactivate(self) -> None:  # pragma: no cover - default no-op
        return None


@dataclass
class PluginState:
    metadata: PluginMetadata
    path: str
    enabled: bool = True
    loaded: bool = False
    initialized: bool = False
    activated: bool = False
    dependencies: List[str] = field(default_factory=list)
    dependents: List[str] = field(default_factory=list)
    error: Optional[str] = None


class PluginContext:
    def __init__(self, name: str, base_path: pathlib.Path, manager: "PluginManager") -> None:
        self.plugin_name = name
        self.plugin_path = str(base_path)
        self.manager = manager

    def register_tool(self, tool: ToolDefinition) -> None:
        self.manager.register_tool(self.plugin_name, tool)

    def get_config(self, key: str, default: Any = None) -> Any:
        return self.manager.get_plugin_config(self.plugin_name).get(key, default)

    def set_config(self, key: str, value: Any) -> None:
        config = self.manager.get_plugin_config(self.plugin_name)
        config[key] = value
        self.manager.set_plugin_config(self.plugin_name, config)


class PluginManager:
    """Discover and manage Python plugin modules."""

    def __init__(self, plugin_dirs: Optional[Iterable[str]] = None) -> None:
        self.plugins: Dict[str, Plugin] = {}
        self.plugin_states: Dict[str, PluginState] = {}
        self.plugin_modules: Dict[str, ModuleType] = {}
        self.plugin_contexts: Dict[str, PluginContext] = {}
        self.plugin_configs: Dict[str, Dict[str, Any]] = {}
        self.registered_tools: Dict[str, List[ToolDefinition]] = {}
        self.plugin_dirs = [
            pathlib.Path(path).expanduser()
            for path in (plugin_dirs or [pathlib.Path.home() / ".claude" / "plugins"])
        ]
        for directory in self.plugin_dirs:
            if str(directory) not in sys.path:
                sys.path.append(str(directory))

    def discover(self) -> List[PluginState]:
        states: List[PluginState] = []
        for directory in self.plugin_dirs:
            if not directory.exists():
                continue
            for entry in directory.iterdir():
                if entry.is_dir() and (entry / "__init__.py").exists():
                    module_name = entry.name
                    metadata = PluginMetadata(name=module_name, version="0.0.0")
                    state = PluginState(metadata=metadata, path=str(entry))
                    self.plugin_states[module_name] = state
                    states.append(state)
        return states

    def load(self, name: str) -> bool:
        state = self.plugin_states.get(name)
        if not state:
            raise PluginError(f"Plugin not found: {name}")
        if state.loaded:
            return True

        try:
            module_path = self._module_path(state)
            module = importlib.import_module(module_path)
            plugin_obj = getattr(module, "plugin", None) or module
            if not hasattr(plugin_obj, "metadata"):
                plugin_obj.metadata = state.metadata
            plugin: Plugin = plugin_obj
            context = PluginContext(name, pathlib.Path(state.path), self)
            if hasattr(plugin, "init"):
                plugin.init(context)
                state.initialized = True
            if hasattr(plugin, "activate"):
                plugin.activate(context)
                state.activated = True
            for tool in getattr(plugin, "tools", []) or []:
                context.register_tool(tool)
            self.plugins[name] = plugin
            self.plugin_modules[name] = module
            self.plugin_contexts[name] = context
            state.loaded = True
            return True
        except Exception as exc:  # noqa: BLE001 - plugin import errors
            state.error = str(exc)
            raise PluginError(f"Failed to load plugin {name}: {exc}") from exc

    def unload(self, name: str) -> bool:
        state = self.plugin_states.get(name)
        plugin = self.plugins.get(name)
        if not state or not plugin:
            return False
        if hasattr(plugin, "deactivate"):
            plugin.deactivate()
        self.registered_tools.pop(name, None)
        self.plugins.pop(name, None)
        self.plugin_modules.pop(name, None)
        self.plugin_contexts.pop(name, None)
        state.loaded = False
        state.initialized = False
        state.activated = False
        return True

    def register_inline_plugin(self, name: str, plugin: Plugin) -> None:
        if name in self.plugins:
            raise PluginError(f"Plugin {name} already registered")
        metadata = plugin.metadata
        state = PluginState(metadata=metadata, path="<inline>", enabled=True)
        self.plugin_states[name] = state
        context = PluginContext(name, pathlib.Path.cwd(), self)
        if hasattr(plugin, "init"):
            plugin.init(context)
            state.initialized = True
        if hasattr(plugin, "activate"):
            plugin.activate(context)
            state.activated = True
        for tool in getattr(plugin, "tools", []) or []:
            context.register_tool(tool)
        self.plugins[name] = plugin
        state.loaded = True

    def register_tool(self, plugin_name: str, tool: ToolDefinition) -> None:
        self.registered_tools.setdefault(plugin_name, []).append(tool)

    def get_tools(self) -> List[ToolDefinition]:
        tools: List[ToolDefinition] = []
        for tool_list in self.registered_tools.values():
            tools.extend(tool_list)
        return tools

    def get_plugin_config(self, name: str) -> Dict[str, Any]:
        return self.plugin_configs.setdefault(name, {})

    def set_plugin_config(self, name: str, config: Dict[str, Any]) -> None:
        self.plugin_configs[name] = config

    def _module_path(self, state: PluginState) -> str:
        return pathlib.Path(state.path).name


class PluginToolExecutor:
    def __init__(self, manager: PluginManager) -> None:
        self.manager = manager
        self.executors: Dict[str, Callable[[Any], ToolResult]] = {}

    def register_tool(self, plugin_name: str, tool: ToolDefinition, executor: Callable[[Any], ToolResult]) -> None:
        self.manager.register_tool(plugin_name, tool)
        self.executors[tool["name"]] = executor

    def execute(self, tool_name: str, payload: Any) -> ToolResult:
        executor = self.executors.get(tool_name)
        if not executor:
            raise PluginError(f"Tool not found: {tool_name}")
        return executor(payload)
