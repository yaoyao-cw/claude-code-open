"""Shared error types for the Python Claude Code API."""
from __future__ import annotations


class ClaudeCodeError(Exception):
    """Base error for Claude Code Python helpers."""


class ConfigError(ClaudeCodeError):
    """Raised when configuration loading or validation fails."""


class AuthError(ClaudeCodeError):
    """Raised when authentication initialization or persistence fails."""


class ClaudePermissionError(ClaudeCodeError):
    """Raised when a permission decision denies an action."""


class PluginError(ClaudeCodeError):
    """Raised when plugin lifecycle operations fail."""


class HookError(ClaudeCodeError):
    """Raised when a hook fails to execute."""
