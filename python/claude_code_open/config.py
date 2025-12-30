"""Configuration loading and merging for the Python Claude Code surface."""
from __future__ import annotations

import json
import os
import pathlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, List, Literal, Optional

from .errors import ConfigError

ConfigSource = Literal[
    "default",
    "userSettings",
    "projectSettings",
    "localSettings",
    "envSettings",
    "flagSettings",
    "policySettings",
    "plugin",
    "built-in",
]

CONFIG_SOURCE_PRIORITY: Dict[ConfigSource, int] = {
    "default": 0,
    "userSettings": 1,
    "projectSettings": 2,
    "localSettings": 3,
    "envSettings": 4,
    "flagSettings": 5,
    "policySettings": 6,
    "plugin": 3,
    "built-in": 0,
}

DEFAULT_CONFIG: Dict[str, Any] = {
    "version": "2.0.76",
    "model": "sonnet",
    "maxTokens": 32000,
    "temperature": 1,
    "theme": "auto",
    "verbose": False,
    "editMode": "default",
    "maxRetries": 3,
    "enableTelemetry": False,
    "disableFileCheckpointing": False,
    "enableAutoSave": True,
    "includeCoAuthoredBy": True,
    "maxConcurrentTasks": 10,
    "requestTimeout": 300000,
    "useBedrock": False,
    "useVertex": False,
}


@dataclass(frozen=True)
class ConfigSourceInfo:
    source: ConfigSource
    priority: int
    path: Optional[str] = None
    exists: Optional[bool] = None
    loaded_at: Optional[datetime] = None


@dataclass(frozen=True)
class ConfigKeySource:
    key: str
    value: Any
    source: ConfigSource
    source_path: Optional[str] = None
    overridden_by: Optional[List[ConfigSource]] = None


def _parse_env_bool(value: Optional[str]) -> Optional[bool]:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes"}:
        return True
    if normalized in {"false", "0", "no"}:
        return False
    return None


def _parse_env_number(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _mask_sensitive_fields(config: Dict[str, Any]) -> Dict[str, Any]:
    masked = dict(config)
    for key in ("apiKey", "oauthToken", "authToken"):
        if key in masked and masked[key]:
            masked[key] = "****"
    return masked


def _deep_merge(base: Any, override: Any) -> Any:
    if override is None:
        return base
    if base is None:
        return override
    if not isinstance(override, dict) or not isinstance(base, dict):
        return override
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            merged[key] = _deep_merge(base[key], value)
        else:
            merged[key] = value
    return merged


def _load_json(path: pathlib.Path) -> Optional[Dict[str, Any]]:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"Failed to load config from {path}: {exc}") from exc
    return None


def _migrate_config(config: Dict[str, Any]) -> Dict[str, Any]:
    version = config.get("version") or "1.0.0"
    migrated = dict(config)
    if version < "2.0.0":
        if migrated.get("model") == "claude-3-opus":
            migrated["model"] = "opus"
        if migrated.get("model") == "claude-3-sonnet":
            migrated["model"] = "sonnet"
        if migrated.get("model") == "claude-3-haiku":
            migrated["model"] = "haiku"
    if version < "2.0.76":
        if "autoSave" in migrated and "enableAutoSave" not in migrated:
            migrated["enableAutoSave"] = migrated.pop("autoSave")
    migrated["version"] = "2.0.76"
    return migrated


class ConfigManager:
    """Load, merge, and track Claude Code configuration sources."""

    def __init__(
        self,
        *,
        working_directory: Optional[str] = None,
        flag_settings_path: Optional[str] = None,
        cli_flags: Optional[Dict[str, Any]] = None,
        debug: bool = False,
    ) -> None:
        self.debug = debug or os.environ.get("CLAUDE_CODE_DEBUG") == "true"
        self.cli_flags = cli_flags or {}

        working_dir = pathlib.Path(working_directory or os.getcwd())
        self.global_config_dir = pathlib.Path(
            os.environ.get("CLAUDE_CONFIG_DIR", pathlib.Path.home() / ".claude")
        )
        self.user_config_file = self.global_config_dir / "settings.json"
        managed_settings = self.global_config_dir / "managed_settings.json"
        policy_json = self.global_config_dir / "policy.json"
        self.policy_config_file = managed_settings if managed_settings.exists() else policy_json
        self.project_config_file = working_dir / ".claude" / "settings.json"
        self.local_config_file = working_dir / ".claude" / "settings.local.json"
        self.flag_config_file = pathlib.Path(flag_settings_path) if flag_settings_path else None

        self._config_sources: Dict[str, ConfigSource] = {}
        self._config_source_paths: Dict[str, str] = {}
        self._config_history: Dict[str, List[ConfigKeySource]] = {}
        self._loaded_sources: List[ConfigSourceInfo] = []
        self._enterprise_policy: Optional[Dict[str, Any]] = None

        self._merged_config = self._load_and_merge()

    def _debug_log(self, message: str) -> None:
        if self.debug:
            print(f"[Config] {message}")

    def _track_sources(self, config: Dict[str, Any], source: ConfigSource, source_path: Optional[str]) -> None:
        def _walk(node: Dict[str, Any], prefix: str = "") -> None:
            for key, value in node.items():
                full_key = f"{prefix}.{key}" if prefix else key
                if isinstance(value, dict):
                    _walk(value, full_key)
                if full_key in self._config_sources and self._config_sources[full_key] != source:
                    history = self._config_history.setdefault(full_key, [])
                    history.append(
                        ConfigKeySource(
                            key=full_key,
                            value=value,
                            source=source,
                            source_path=source_path,
                            overridden_by=[self._config_sources[full_key]],
                        )
                    )
                self._config_sources[full_key] = source
                if source_path:
                    self._config_source_paths[full_key] = source_path

        _walk(config)

    def _merge(self, base: Dict[str, Any], override: Dict[str, Any], source: ConfigSource, path: Optional[str]) -> Dict[str, Any]:
        merged = _deep_merge(base, override)
        self._track_sources(override, source, path)
        return merged

    def _load_enterprise_policy(self) -> Optional[Dict[str, Any]]:
        try:
            policy = _load_json(self.policy_config_file)
        except ConfigError as exc:
            self._debug_log(str(exc))
            return None
        if policy:
            self._debug_log(f"Loaded enterprise policy from {self.policy_config_file}")
        return policy

    def _env_config(self) -> Dict[str, Any]:
        config: Dict[str, Any] = {
            "apiKey": os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY"),
            "oauthToken": os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"),
            "useBedrock": _parse_env_bool(os.environ.get("CLAUDE_CODE_USE_BEDROCK")),
            "useVertex": _parse_env_bool(os.environ.get("CLAUDE_CODE_USE_VERTEX")),
            "maxTokens": _parse_env_number(os.environ.get("CLAUDE_CODE_MAX_OUTPUT_TOKENS")),
            "maxRetries": _parse_env_number(os.environ.get("CLAUDE_CODE_MAX_RETRIES")),
            "debugLogsDir": os.environ.get("CLAUDE_CODE_DEBUG_LOGS_DIR"),
            "enableTelemetry": _parse_env_bool(os.environ.get("CLAUDE_CODE_ENABLE_TELEMETRY")),
            "disableFileCheckpointing": _parse_env_bool(
                os.environ.get("CLAUDE_CODE_DISABLE_FILE_CHECKPOINTING")
            ),
            "agentId": os.environ.get("CLAUDE_CODE_AGENT_ID"),
        }
        if _parse_env_bool(os.environ.get("CLAUDE_CODE_USE_BEDROCK")):
            config["apiProvider"] = "bedrock"
        elif _parse_env_bool(os.environ.get("CLAUDE_CODE_USE_VERTEX")):
            config["apiProvider"] = "vertex"
        if os.environ.get("CLAUDE_CODE_OTEL_SHUTDOWN_TIMEOUT_MS"):
            config["telemetry"] = {
                "otelShutdownTimeoutMs": _parse_env_number(
                    os.environ.get("CLAUDE_CODE_OTEL_SHUTDOWN_TIMEOUT_MS")
                )
            }
        if os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY"):
            config["proxy"] = {
                "http": os.environ.get("HTTP_PROXY"),
                "https": os.environ.get("HTTPS_PROXY"),
            }
        return {key: value for key, value in config.items() if value is not None}

    def _load_and_merge(self) -> Dict[str, Any]:
        self._config_sources.clear()
        self._config_source_paths.clear()
        self._config_history.clear()
        self._loaded_sources.clear()
        load_time = datetime.now()

        config = dict(DEFAULT_CONFIG)
        self._track_sources(config, "default", None)
        self._loaded_sources.append(
            ConfigSourceInfo(source="default", priority=CONFIG_SOURCE_PRIORITY["default"], exists=True, loaded_at=load_time)
        )

        self._enterprise_policy = self._load_enterprise_policy()
        if self._enterprise_policy and self._enterprise_policy.get("defaults"):
            config = self._merge(
                config,
                self._enterprise_policy["defaults"],
                "policySettings",
                str(self.policy_config_file),
            )

        def _merge_file(path: pathlib.Path, source: ConfigSource) -> None:
            exists = path.exists()
            self._loaded_sources.append(
                ConfigSourceInfo(
                    source=source,
                    priority=CONFIG_SOURCE_PRIORITY[source],
                    path=str(path),
                    exists=exists,
                    loaded_at=load_time,
                )
            )
            if exists:
                data = _load_json(path)
                if data:
                    nonlocal config
                    config = self._merge(config, data, source, str(path))
                    self._debug_log(f"Loaded {source} from {path}")

        _merge_file(self.user_config_file, "userSettings")
        _merge_file(self.project_config_file, "projectSettings")
        _merge_file(self.local_config_file, "localSettings")

        env_config = self._env_config()
        if env_config:
            config = self._merge(config, env_config, "envSettings", None)
            self._loaded_sources.append(
                ConfigSourceInfo(
                    source="envSettings",
                    priority=CONFIG_SOURCE_PRIORITY["envSettings"],
                    exists=True,
                    loaded_at=load_time,
                )
            )

        if self.flag_config_file:
            _merge_file(self.flag_config_file, "flagSettings")

        if self.cli_flags:
            config = self._merge(config, self.cli_flags, "flagSettings", None)

        if self._enterprise_policy and self._enterprise_policy.get("enforced"):
            config = self._merge(
                config,
                self._enterprise_policy["enforced"],
                "policySettings",
                str(self.policy_config_file),
            )
            self._loaded_sources.append(
                ConfigSourceInfo(
                    source="policySettings",
                    priority=CONFIG_SOURCE_PRIORITY["policySettings"],
                    path=str(self.policy_config_file),
                    exists=True,
                    loaded_at=load_time,
                )
            )

        return _migrate_config(config)

    def reload(self) -> None:
        self._merged_config = self._load_and_merge()

    def get(self, key: str) -> Any:
        return self._merged_config.get(key)

    def get_all(self) -> Dict[str, Any]:
        return dict(self._merged_config)

    def get_with_source(self, key: str) -> ConfigKeySource:
        return ConfigKeySource(
            key=key,
            value=self._merged_config.get(key),
            source=self._config_sources.get(key, "default"),
            source_path=self._config_source_paths.get(key),
            overridden_by=[entry.source for entry in self._config_history.get(key, [])] or None,
        )

    def export(self, mask_secrets: bool = True) -> str:
        data = dict(self._merged_config)
        if mask_secrets:
            data = _mask_sensitive_fields(data)
        return json.dumps(data, indent=2, ensure_ascii=False)

    def get_source_info(self) -> List[ConfigSourceInfo]:
        return list(self._loaded_sources)

    def get_all_config_details(self) -> List[ConfigKeySource]:
        details: List[ConfigKeySource] = []
        for key in self._config_sources:
            details.append(self.get_with_source(key))
        return details

    def apply_plugin_config(self, plugin_config: Dict[str, Any]) -> None:
        self._merged_config = self._merge(self._merged_config, plugin_config, "plugin", None)


def load_config(
    *,
    working_directory: Optional[str] = None,
    flag_settings_path: Optional[str] = None,
    cli_flags: Optional[Dict[str, Any]] = None,
    debug: bool = False,
) -> ConfigManager:
    return ConfigManager(
        working_directory=working_directory,
        flag_settings_path=flag_settings_path,
        cli_flags=cli_flags,
        debug=debug,
    )
