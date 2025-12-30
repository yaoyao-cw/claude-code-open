"""Hook registry and execution pipeline for Python Claude Code."""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Literal, Optional
from urllib import request as urlrequest

from .errors import HookError

HookEvent = Literal[
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "Notification",
    "UserPromptSubmit",
    "SessionStart",
    "SessionEnd",
    "Stop",
    "SubagentStart",
    "SubagentStop",
    "PreCompact",
    "PermissionRequest",
    "BeforeSetup",
    "AfterSetup",
    "CommandsLoaded",
    "ToolsLoaded",
    "McpConfigsLoaded",
    "PluginsInitialized",
    "AfterHooks",
]

HookType = Literal["command", "url", "callable"]


@dataclass
class HookConfig:
    type: HookType
    handler: Optional[Callable[[Dict[str, Any]], "HookResult"]] = None
    command: Optional[str] = None
    args: Optional[List[str]] = None
    url: Optional[str] = None
    method: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    timeout: Optional[int] = None
    blocking: bool = True
    matcher: Optional[str] = None


@dataclass
class HookResult:
    success: bool
    output: Optional[str] = None
    error: Optional[str] = None
    blocked: bool = False
    block_message: Optional[str] = None


class HookRegistry:
    def __init__(self) -> None:
        self._hooks: Dict[HookEvent, List[HookConfig]] = {}

    def register(self, event: HookEvent, config: HookConfig) -> None:
        self._hooks.setdefault(event, []).append(config)

    def unregister(self, event: HookEvent, config: HookConfig) -> bool:
        hooks = self._hooks.get(event, [])
        if config in hooks:
            hooks.remove(config)
            return True
        return False

    def load_from_config(self, config: Dict[str, Any]) -> None:
        hooks = config.get("hooks") or {}
        if isinstance(hooks, dict):
            for event, entries in hooks.items():
                for entry in entries if isinstance(entries, list) else [entries]:
                    self.register(event, HookConfig(**entry))

    def run(self, event: HookEvent, payload: Dict[str, Any]) -> List[HookResult]:
        results: List[HookResult] = []
        for hook in self._hooks.get(event, []):
            if hook.matcher and payload.get("toolName") and hook.matcher != payload["toolName"]:
                continue
            result = self._execute(hook, payload)
            results.append(result)
            if result.blocked and hook.blocking:
                break
        return results

    def _execute(self, hook: HookConfig, payload: Dict[str, Any]) -> HookResult:
        if hook.type == "command":
            return self._execute_command(hook, payload)
        if hook.type == "url":
            return self._execute_url(hook, payload)
        if hook.type == "callable" and hook.handler:
            try:
                return hook.handler(payload)
            except Exception as exc:  # noqa: BLE001 - user hook errors
                return HookResult(False, error=str(exc))
        raise HookError(f"Unsupported hook type: {hook.type}")

    def _execute_command(self, hook: HookConfig, payload: Dict[str, Any]) -> HookResult:
        if not hook.command:
            return HookResult(False, error="Command hook missing command")
        env = os.environ.copy()
        env["CLAUDE_HOOK_EVENT"] = payload.get("event", "")
        env["CLAUDE_HOOK_TOOL_NAME"] = payload.get("toolName", "")
        input_json = json.dumps(payload)
        try:
            proc = subprocess.run(
                [hook.command, *(hook.args or [])],
                input=input_json.encode("utf-8"),
                capture_output=True,
                env=env,
                timeout=hook.timeout or 30,
            )
        except subprocess.TimeoutExpired:
            return HookResult(False, error="Hook execution timed out")
        if proc.returncode != 0:
            return HookResult(False, error=proc.stderr.decode("utf-8"))
        return HookResult(True, output=proc.stdout.decode("utf-8"))

    def _execute_url(self, hook: HookConfig, payload: Dict[str, Any]) -> HookResult:
        if not hook.url:
            return HookResult(False, error="URL hook missing url")
        data = json.dumps(payload).encode("utf-8")
        req = urlrequest.Request(
            hook.url,
            data=data if (hook.method or "POST").upper() != "GET" else None,
            headers={"Content-Type": "application/json", **(hook.headers or {})},
            method=(hook.method or "POST").upper(),
        )
        try:
            with urlrequest.urlopen(req, timeout=hook.timeout or 10) as response:
                body = response.read().decode("utf-8")
        except Exception as exc:  # noqa: BLE001 - network errors
            return HookResult(False, error=str(exc))
        return HookResult(True, output=body)


def run_pre_tool_use_hooks(
    registry: HookRegistry,
    tool_name: str,
    tool_input: Any,
    session_id: Optional[str] = None,
) -> List[HookResult]:
    payload = {
        "event": "PreToolUse",
        "toolName": tool_name,
        "toolInput": tool_input,
        "sessionId": session_id,
    }
    return registry.run("PreToolUse", payload)
