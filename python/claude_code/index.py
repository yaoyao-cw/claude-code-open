"""
Claude Code (Python) entrypoint.

Aggregates exports and provides CLI startup logic analogous to src/index.ts.
"""

from .cli import main as cli_main
from .config import ConfigManager, config_manager
from .core import ClaudeClient, ConversationLoop, MessageResponse, start_session
from .plugins import PluginManager, plugin_manager
from .session import Session, SessionManager, SessionStats, session_manager

VERSION = "2.0.76-restored"
NAME = "claude-code-restored"

__all__ = [
    "ClaudeClient",
    "ConversationLoop",
    "MessageResponse",
    "start_session",
    "ConfigManager",
    "config_manager",
    "PluginManager",
    "plugin_manager",
    "Session",
    "SessionManager",
    "SessionStats",
    "session_manager",
    "VERSION",
    "NAME",
    "cli_main",
]
