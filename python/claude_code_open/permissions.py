"""Permission checking for tools, paths, commands, and network access."""
from __future__ import annotations

import fnmatch
import json
import os
import pathlib
from dataclasses import dataclass
from datetime import datetime
from functools import wraps
from typing import Callable, Dict, List, Literal, Optional, TypeVar

from .errors import ClaudePermissionError

PermissionMode = Literal[
    "default",
    "bypassPermissions",
    "dontAsk",
    "acceptEdits",
    "plan",
    "delegate",
]

PermissionType = Literal[
    "file_read",
    "file_write",
    "file_delete",
    "bash_command",
    "network_request",
    "mcp_server",
    "plugin_install",
    "system_config",
]


@dataclass
class PermissionRequest:
    type: PermissionType
    tool: str
    description: str
    resource: Optional[str] = None


@dataclass
class PermissionDecision:
    allowed: bool
    reason: Optional[str] = None
    remember: bool = False
    scope: Optional[Literal["once", "session", "always"]] = None


@dataclass
class PermissionRule:
    type: PermissionType
    action: Literal["allow", "deny", "ask"]
    pattern: Optional[str] = None


class PermissionManager:
    """Evaluate permission requests using config, rules, and remembered decisions."""

    def __init__(self, mode: PermissionMode = "default", interactive: bool = False) -> None:
        self.mode = mode
        self.interactive = interactive
        self.rules: List[PermissionRule] = []
        self.remembered: Dict[str, bool] = {}
        self.session_decisions: Dict[str, bool] = {}
        self.allowed_dirs: List[str] = []
        self.permission_config: Dict[str, Dict[str, List[str]]] = {}
        self.config_dir = pathlib.Path(
            os.environ.get("CLAUDE_CONFIG_DIR", pathlib.Path.home() / ".claude")
        )
        self.audit_enabled = False
        self.audit_log_path = self.config_dir / "permissions-audit.log"

        self._load_permission_config()
        self._load_persisted()
        self._setup_default_rules()

    def set_mode(self, mode: PermissionMode) -> None:
        self.mode = mode

    def add_allowed_dir(self, directory: str) -> None:
        resolved = str(pathlib.Path(directory).resolve())
        if resolved not in self.allowed_dirs:
            self.allowed_dirs.append(resolved)

    def is_path_allowed(self, file_path: str) -> bool:
        resolved = str(pathlib.Path(file_path).resolve())
        cwd = str(pathlib.Path.cwd())
        if resolved.startswith(cwd):
            return True
        return any(resolved.startswith(directory) for directory in self.allowed_dirs)

    def check(self, request: PermissionRequest) -> PermissionDecision:
        if self.mode == "bypassPermissions":
            return self._finalize(request, PermissionDecision(True, reason="Permissions bypassed"))
        if self.mode == "plan":
            return self._finalize(request, PermissionDecision(False, reason="Plan mode - no execution"))
        if self.mode == "dontAsk":
            return self._finalize(request, self._auto_decide(request))
        if self.mode == "acceptEdits" and request.type in {"file_read", "file_write"}:
            return self._finalize(request, PermissionDecision(True, reason="Auto-accept edits mode"))

        decision = self._check_with_rules(request)
        return self._finalize(request, decision)

    def _auto_decide(self, request: PermissionRequest) -> PermissionDecision:
        if request.type == "file_read":
            return PermissionDecision(True, reason="Auto-allow reads")
        if request.resource and request.type in {"file_write", "file_delete"}:
            if self.is_path_allowed(request.resource):
                return PermissionDecision(True, reason="Path allowed")
        return PermissionDecision(False, reason="Auto-denied in dontAsk mode")

    def _check_with_rules(self, request: PermissionRequest) -> PermissionDecision:
        tool_decision = self._check_config_list("tools", request.tool)
        if tool_decision is not None:
            return PermissionDecision(tool_decision, reason="Tool decision from config")

        if request.resource and request.type in {"file_read", "file_write", "file_delete"}:
            path_decision = self._check_config_list("paths", request.resource)
            if path_decision is not None:
                return PermissionDecision(path_decision, reason="Path decision from config")

        if request.type == "bash_command" and request.resource:
            cmd_decision = self._check_config_list("commands", request.resource)
            if cmd_decision is not None:
                return PermissionDecision(cmd_decision, reason="Command decision from config")

        if request.type == "network_request" and request.resource:
            net_decision = self._check_config_list("network", request.resource)
            if net_decision is not None:
                return PermissionDecision(net_decision, reason="Network decision from config")

        key = self._permission_key(request)
        if key in self.remembered:
            return PermissionDecision(self.remembered[key], reason="Remembered decision")
        if key in self.session_decisions:
            return PermissionDecision(self.session_decisions[key], reason="Session decision")

        for rule in self.rules:
            if self._rule_matches(rule, request):
                if rule.action == "allow":
                    return PermissionDecision(True, reason="Matched allow rule")
                if rule.action == "deny":
                    return PermissionDecision(False, reason="Matched deny rule")
                break

        if self.interactive:
            return self._ask_user(request)
        return PermissionDecision(False, reason="No rule matched")

    def _permission_key(self, request: PermissionRequest) -> str:
        return f"{request.type}:{request.resource or '*'}"

    def _rule_matches(self, rule: PermissionRule, request: PermissionRequest) -> bool:
        if rule.type != request.type:
            return False
        if not rule.pattern:
            return True
        return request.resource is not None and rule.pattern in request.resource

    def _ask_user(self, request: PermissionRequest) -> PermissionDecision:
        prompt = f"Allow {request.tool} ({request.type})? [y/N]: "
        choice = input(prompt).strip().lower()
        if choice == "y":
            return PermissionDecision(True, reason="User allowed", scope="once")
        return PermissionDecision(False, reason="User denied", scope="once")

    def _finalize(self, request: PermissionRequest, decision: PermissionDecision) -> PermissionDecision:
        if decision.remember and decision.scope in {"session", "always"}:
            key = self._permission_key(request)
            if decision.scope == "session":
                self.session_decisions[key] = decision.allowed
            else:
                self.remembered[key] = decision.allowed
                self._persist()
        self._log_audit(request, decision)
        return decision

    def _setup_default_rules(self) -> None:
        self.rules = [
            PermissionRule(type="file_read", action="allow"),
            PermissionRule(type="bash_command", action="allow", pattern="ls"),
            PermissionRule(type="bash_command", action="allow", pattern="cat"),
            PermissionRule(type="file_delete", action="ask"),
            PermissionRule(type="bash_command", action="ask", pattern="rm"),
            PermissionRule(type="network_request", action="ask"),
            PermissionRule(type="mcp_server", action="ask"),
            PermissionRule(type="plugin_install", action="ask"),
            PermissionRule(type="system_config", action="ask"),
        ]

    def _persist(self) -> None:
        self.config_dir.mkdir(parents=True, exist_ok=True)
        path = self.config_dir / "permissions.json"
        path.write_text(json.dumps(self.remembered, indent=2), encoding="utf-8")

    def _load_persisted(self) -> None:
        path = self.config_dir / "permissions.json"
        if path.exists():
            try:
                self.remembered = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self.remembered = {}

    def _load_permission_config(self) -> None:
        settings_path = self.config_dir / "settings.json"
        if not settings_path.exists():
            return
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return
        permissions = settings.get("permissions") or {}
        self.permission_config = permissions
        if permissions.get("defaultMode"):
            self.mode = permissions.get("defaultMode")
        if permissions.get("additionalDirectories"):
            for directory in permissions["additionalDirectories"]:
                self.add_allowed_dir(directory)
        audit = permissions.get("audit") or {}
        if audit.get("enabled"):
            self.audit_enabled = True
            if audit.get("logFile"):
                self.audit_log_path = pathlib.Path(audit["logFile"]).expanduser().resolve()

    def _check_config_list(self, key: str, value: str) -> Optional[bool]:
        config = self.permission_config.get(key) or {}
        deny_list = config.get("deny") or []
        allow_list = config.get("allow") or []
        for pattern in deny_list:
            if fnmatch.fnmatch(value, pattern) or value == pattern:
                return False
        if allow_list:
            for pattern in allow_list:
                if fnmatch.fnmatch(value, pattern) or value == pattern:
                    return True
            return False
        return None

    def _log_audit(self, request: PermissionRequest, decision: PermissionDecision) -> None:
        if not self.audit_enabled:
            return
        entry = {
            "timestamp": datetime.now().isoformat(),
            "type": request.type,
            "tool": request.tool,
            "resource": request.resource,
            "decision": "allow" if decision.allowed else "deny",
            "reason": decision.reason,
        }
        self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.audit_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")

T = TypeVar("T")


def requires_permission(
    permission_type: PermissionType, description: str, manager: Optional[PermissionManager] = None
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: object, **kwargs: object) -> T:
            perm_manager = manager or PermissionManager()
            request = PermissionRequest(
                type=permission_type,
                tool=func.__name__,
                description=description,
            )
            decision = perm_manager.check(request)
            if not decision.allowed:
                raise ClaudePermissionError(decision.reason or "Permission denied")
            return func(*args, **kwargs)

        return wrapper

    return decorator
