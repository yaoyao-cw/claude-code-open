from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from .config import config_manager
from .core import ClaudeClient, ConversationLoop, start_session
from .plugins import plugin_manager
from .session import session_manager


VERSION = "2.0.76-restored"


def _load_api_key() -> str | None:
    env_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY")
    if env_key:
        return env_key
    credentials_file = Path.home() / ".claude" / "credentials.json"
    if credentials_file.exists():
        try:
            data = json.loads(credentials_file.read_text(encoding="utf-8"))
            return data.get("apiKey") or data.get("api_key")
        except json.JSONDecodeError:
            return None
    return None


def _print_json(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _handle_default(args: argparse.Namespace) -> int:
    api_key = _load_api_key()
    client = ClaudeClient(api_key=api_key)
    session = start_session(os.getcwd())
    loop = ConversationLoop(session=session, client=client)

    if args.print:
        if not args.prompt:
            sys.stderr.write("Error: --print requires a prompt.\n")
            return 1
        response = loop.process_message(
            args.prompt,
            model=args.model,
            max_tokens=int(args.max_tokens),
            system_prompt=args.system_prompt,
        )
        if args.output_format == "json":
            _print_json(
                {
                    "content": response.content,
                    "model": response.model,
                    "usage": {
                        "input_tokens": response.input_tokens,
                        "output_tokens": response.output_tokens,
                    },
                    "stop_reason": response.stop_reason,
                }
            )
        elif args.output_format == "stream-json":
            _print_json({"type": "text", "content": response.content})
            _print_json({"type": "done"})
        else:
            sys.stdout.write(response.content + "\n")
        return 0

    if args.prompt:
        response = loop.process_message(
            args.prompt,
            model=args.model,
            max_tokens=int(args.max_tokens),
            system_prompt=args.system_prompt,
        )
        sys.stdout.write(response.content + "\n")
        return 0

    sys.stdout.write("Claude Code (Python) interactive session. Type 'exit' to quit.\n")
    while True:
        try:
            message = input("> ").strip()
        except EOFError:
            sys.stdout.write("\n")
            break
        if message.lower() in {"exit", "quit"}:
            stats = session.get_stats()
            sys.stdout.write(f"Goodbye! Session stats: {stats.message_count} messages.\n")
            break
        if not message:
            continue
        response = loop.process_message(
            message,
            model=args.model,
            max_tokens=int(args.max_tokens),
            system_prompt=args.system_prompt,
        )
        sys.stdout.write(response.content + "\n")
    return 0


def _handle_mcp_list(_: argparse.Namespace) -> int:
    servers = config_manager.get_mcp_servers()
    if not servers:
        sys.stdout.write("No MCP servers configured.\n")
        return 0
    sys.stdout.write("Configured MCP Servers:\n")
    for name, config in servers.items():
        sys.stdout.write(f"  {name}\n")
        sys.stdout.write(f"    Type: {config.get('type')}\n")
        if config.get("command"):
            args = " ".join(config.get("args", []))
            sys.stdout.write(f"    Command: {config['command']} {args}\n")
        if config.get("url"):
            sys.stdout.write(f"    URL: {config['url']}\n")
    return 0


def _handle_mcp_add(args: argparse.Namespace) -> int:
    env_pairs = {}
    if args.env:
        for item in args.env:
            key, _, value = item.partition("=")
            env_pairs[key] = value
    config_manager.add_mcp_server(
        args.name,
        {
            "type": "stdio",
            "command": args.command,
            "args": args.args or [],
            "env": env_pairs,
        },
    )
    sys.stdout.write(f"✓ Added MCP server: {args.name}\n")
    return 0


def _handle_mcp_remove(args: argparse.Namespace) -> int:
    if config_manager.remove_mcp_server(args.name):
        sys.stdout.write(f"✓ Removed MCP server: {args.name}\n")
        return 0
    sys.stderr.write(f"MCP server not found: {args.name}\n")
    return 1


def _handle_tools(_: argparse.Namespace) -> int:
    sys.stdout.write("Tools listing is provided by the Node implementation.\n")
    sys.stdout.write("Use the main CLI to see registered tools.\n")
    return 0


def _handle_sessions(args: argparse.Namespace) -> int:
    sessions = session_manager.list_sessions(limit=int(args.limit), search=args.search)
    if not sessions:
        sys.stdout.write("No saved sessions found.\n")
        return 0
    sys.stdout.write("Saved Sessions:\n")
    for session in sessions:
        sys.stdout.write(f"  {session.session_id}\n")
        if session.name:
            sys.stdout.write(f"    Name: {session.name}\n")
        sys.stdout.write(f"    Created: {session.created_at}\n")
        sys.stdout.write(f"    Directory: {session.working_directory}\n")
        sys.stdout.write(f"    Messages: {len(session.messages)}\n")
    return 0


def _handle_doctor(_: argparse.Namespace) -> int:
    sys.stdout.write("Running Claude Code diagnostics (Python)...\n")
    api_key = _load_api_key()
    if api_key:
        sys.stdout.write("✓ API key detected\n")
    else:
        sys.stdout.write("⚠ No API key configured\n")
    sys.stdout.write(f"Working directory: {os.getcwd()}\n")
    return 0


def _handle_setup_token(_: argparse.Namespace) -> int:
    api_key = input("Enter your API key: ").strip()
    if not api_key:
        sys.stdout.write("No API key provided.\n")
        return 1
    credentials_file = Path.home() / ".claude" / "credentials.json"
    credentials_file.parent.mkdir(parents=True, exist_ok=True)
    credentials_file.write_text(json.dumps({"apiKey": api_key}, indent=2), encoding="utf-8")
    sys.stdout.write("✓ API key saved successfully.\n")
    return 0


def _handle_update(args: argparse.Namespace) -> int:
    sys.stdout.write("Update management is handled by the Node CLI.\n")
    if args.list_versions:
        sys.stdout.write("Use the Node CLI to list versions.\n")
    return 0


def _handle_install(args: argparse.Namespace) -> int:
    version = args.target or "stable"
    sys.stdout.write(f"Installing Claude Code ({version})...\n")
    sys.stdout.write("For native builds, please visit:\n")
    sys.stdout.write("https://github.com/anthropics/claude-code\n")
    return 0


def _handle_github_setup(_: argparse.Namespace) -> int:
    sys.stdout.write("GitHub Actions setup is available in the Node CLI.\n")
    return 0


def _handle_review_pr(args: argparse.Namespace) -> int:
    sys.stdout.write(f"Reviewing PR #{args.number}...\n")
    sys.stdout.write("Use the Node CLI for GitHub integration.\n")
    return 0


def _handle_provider(_: argparse.Namespace) -> int:
    sys.stdout.write("Provider inspection is available in the Node CLI.\n")
    return 0


def _handle_checkpoint(args: argparse.Namespace) -> int:
    action = args.action or "list"
    if action == "list":
        sys.stdout.write("Checkpoint listing is available in the Node CLI.\n")
        return 0
    if action == "restore":
        sys.stdout.write("Checkpoint restore is available in the Node CLI.\n")
        return 0
    if action == "clear":
        sys.stdout.write("Checkpoint clearing is available in the Node CLI.\n")
        return 0
    sys.stderr.write("Usage: claude checkpoint [list|restore <file>|clear]\n")
    return 1


def _handle_login(args: argparse.Namespace) -> int:
    if not args.api_key and not args.oauth and not args.claudeai and not args.console:
        sys.stdout.write("Login methods:\n")
        sys.stdout.write("  claude login --api-key\n")
        sys.stdout.write("  claude login --oauth\n")
        sys.stdout.write("  claude login --claudeai\n")
        sys.stdout.write("  claude login --console\n")
        return 0
    if args.api_key:
        sys.stdout.write("Use `claude setup-token` to store an API key.\n")
        return 0
    sys.stdout.write("OAuth flow is implemented in the Node CLI.\n")
    return 0


def _handle_logout(_: argparse.Namespace) -> int:
    credentials_file = Path.home() / ".claude" / "credentials.json"
    if credentials_file.exists():
        credentials_file.unlink()
        sys.stdout.write("✓ Cleared stored API token\n")
    else:
        sys.stdout.write("No stored token file found.\n")
    return 0


def _handle_api_query(args: argparse.Namespace) -> int:
    api_key = _load_api_key()
    if not api_key:
        sys.stderr.write("❌ No API key found. Use `claude setup-token`.\n")
        return 1
    client = ClaudeClient(api_key=api_key)
    response = client.send_message(
        " ".join(args.query),
        model=args.model,
        max_tokens=1024,
    )
    sys.stdout.write(response.content + "\n")
    return 0


def _handle_api_models(_: argparse.Namespace) -> int:
    sys.stdout.write("Available models:\n")
    sys.stdout.write("  claude-sonnet-4-5-20250929\n")
    sys.stdout.write("  claude-opus-4-5-20251101\n")
    sys.stdout.write("  claude-haiku-4-5-20250514\n")
    return 0


def _handle_api_test(_: argparse.Namespace) -> int:
    api_key = _load_api_key()
    if not api_key:
        sys.stderr.write("❌ API Key Not Found\n")
        return 1
    client = ClaudeClient(api_key=api_key)
    response = client.send_message("Hello", model="claude-haiku-4-5-20250514", max_tokens=10)
    sys.stdout.write("✅ API Connection Successful\n")
    if response.model:
        sys.stdout.write(f"Model: {response.model}\n")
    return 0


def _handle_tokens_status(_: argparse.Namespace) -> int:
    env_key = os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY")
    credentials_file = Path.home() / ".claude" / "credentials.json"
    if env_key:
        sys.stdout.write(f"✓ Environment Variable: {env_key[:20]}...\n")
    else:
        sys.stdout.write("✗ Environment Variable: Not set\n")
    if credentials_file.exists():
        sys.stdout.write("✓ File Token: ~/.claude/credentials.json\n")
    else:
        sys.stdout.write("✗ File Token: Not found\n")
    return 0


def _handle_tokens_clear(_: argparse.Namespace) -> int:
    credentials_file = Path.home() / ".claude" / "credentials.json"
    if credentials_file.exists():
        credentials_file.unlink()
        sys.stdout.write("✅ Cleared stored API token\n")
    else:
        sys.stdout.write("No stored token file found.\n")
    return 0


def _handle_plugin_list(args: argparse.Namespace) -> int:
    plugins = plugin_manager.list_plugins()
    if not plugins:
        sys.stdout.write("No plugins found.\n")
        return 0
    for plugin in plugins:
        if not args.all and not plugin.enabled:
            continue
        status = "✓ Loaded" if plugin.loaded else ("○ Enabled" if plugin.enabled else "✗ Disabled")
        sys.stdout.write(f"{plugin.name} {plugin.version} {status}\n")
    return 0


def _handle_plugin_install(args: argparse.Namespace) -> int:
    state = plugin_manager.install(args.plugin)
    sys.stdout.write(f"✓ Successfully installed plugin: {state.name}@{state.version}\n")
    return 0


def _handle_plugin_remove(args: argparse.Namespace) -> int:
    if plugin_manager.remove(args.plugin):
        sys.stdout.write(f"✓ Successfully removed plugin: {args.plugin}\n")
        return 0
    sys.stderr.write(f"✗ Plugin not found: {args.plugin}\n")
    return 1


def _handle_plugin_enable(args: argparse.Namespace) -> int:
    if plugin_manager.enable(args.plugin):
        sys.stdout.write(f"✓ Enabled plugin: {args.plugin}\n")
        return 0
    sys.stderr.write(f"✗ Plugin not found: {args.plugin}\n")
    return 1


def _handle_plugin_disable(args: argparse.Namespace) -> int:
    if plugin_manager.disable(args.plugin):
        sys.stdout.write(f"✓ Disabled plugin: {args.plugin}\n")
        return 0
    sys.stderr.write(f"✗ Plugin not found: {args.plugin}\n")
    return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="claude",
        description="Claude Code - starts an interactive session by default, use -p/--print for non-interactive output",
    )
    parser.add_argument("prompt", nargs="?", help="Your prompt")
    parser.add_argument("-v", "--version", action="version", version=VERSION)
    parser.add_argument("-d", "--debug", nargs="?", const="*", help="Enable debug mode with optional category filtering")
    parser.add_argument("--verbose", action="store_true", help="Override verbose mode setting from config")
    parser.add_argument("-p", "--print", dest="print", action="store_true", help="Print response and exit")
    parser.add_argument(
        "--output-format",
        choices=["text", "json", "stream-json"],
        default="text",
        help="Output format (only works with --print)",
    )
    parser.add_argument("--json-schema", help="JSON Schema for structured output validation")
    parser.add_argument("--include-partial-messages", action="store_true")
    parser.add_argument(
        "--input-format",
        choices=["text", "stream-json"],
        default="text",
        help="Input format (only works with --print)",
    )
    parser.add_argument("--dangerously-skip-permissions", action="store_true")
    parser.add_argument("--allow-dangerously-skip-permissions", action="store_true")
    parser.add_argument("--max-budget-usd")
    parser.add_argument("--replay-user-messages", action="store_true")
    parser.add_argument("--allowed-tools", "--allowedTools", nargs="*")
    parser.add_argument("--tools", nargs="*")
    parser.add_argument("--disallowed-tools", "--disallowedTools", nargs="*")
    parser.add_argument("--mcp-config", nargs="*")
    parser.add_argument("--mcp-debug", action="store_true")
    parser.add_argument("--strict-mcp-config", action="store_true")
    parser.add_argument("--system-prompt")
    parser.add_argument("--system-prompt-file")
    parser.add_argument("--append-system-prompt")
    parser.add_argument("--append-system-prompt-file")
    parser.add_argument(
        "--permission-mode",
        choices=["acceptEdits", "bypassPermissions", "default", "delegate", "dontAsk", "plan"],
    )
    parser.add_argument("-c", "--continue", dest="continue_session", action="store_true")
    parser.add_argument("-r", "--resume", nargs="?", const=True)
    parser.add_argument("--fork-session", action="store_true")
    parser.add_argument("--no-session-persistence", action="store_true")
    parser.add_argument("--session-id")
    parser.add_argument("-m", "--model", default="sonnet")
    parser.add_argument("--agent")
    parser.add_argument("--betas", nargs="*")
    parser.add_argument("--fallback-model")
    parser.add_argument("--max-tokens", default="32000")
    parser.add_argument("--settings")
    parser.add_argument("--add-dir", nargs="*")
    parser.add_argument("--ide", action="store_true")
    parser.add_argument("--agents")
    parser.add_argument("--teleport")
    parser.add_argument("--include-dependencies", action="store_true")
    parser.add_argument("--solo", action="store_true")
    parser.add_argument("--setting-sources")
    parser.add_argument("--plugin-dir", nargs="*")
    parser.add_argument("--disable-slash-commands", action="store_true")
    chrome_group = parser.add_mutually_exclusive_group()
    chrome_group.add_argument("--chrome", action="store_true")
    chrome_group.add_argument("--no-chrome", action="store_true")
    parser.add_argument("--text", action="store_true")

    subparsers = parser.add_subparsers(dest="command")

    mcp_parser = subparsers.add_parser("mcp", help="Configure and manage MCP servers")
    mcp_sub = mcp_parser.add_subparsers(dest="mcp_command")

    mcp_list = mcp_sub.add_parser("list", help="List configured MCP servers")
    mcp_list.set_defaults(func=_handle_mcp_list)

    mcp_add = mcp_sub.add_parser("add", help="Add an MCP server")
    mcp_add.add_argument("name")
    mcp_add.add_argument("command")
    mcp_add.add_argument("-s", "--scope", default="local")
    mcp_add.add_argument("-a", "--args", nargs="*")
    mcp_add.add_argument("-e", "--env", nargs="*")
    mcp_add.set_defaults(func=_handle_mcp_add)

    mcp_remove = mcp_sub.add_parser("remove", help="Remove an MCP server")
    mcp_remove.add_argument("name")
    mcp_remove.set_defaults(func=_handle_mcp_remove)

    tools_parser = subparsers.add_parser("tools", help="List available tools")
    tools_parser.set_defaults(func=_handle_tools)

    sessions_parser = subparsers.add_parser("sessions", help="List previous sessions")
    sessions_parser.add_argument("-l", "--limit", default="20")
    sessions_parser.add_argument("-s", "--search")
    sessions_parser.set_defaults(func=_handle_sessions)

    doctor_parser = subparsers.add_parser("doctor", help="Check installation health")
    doctor_parser.add_argument("--verbose", action="store_true")
    doctor_parser.set_defaults(func=_handle_doctor)

    setup_token_parser = subparsers.add_parser("setup-token", help="Set up a long-lived token")
    setup_token_parser.set_defaults(func=_handle_setup_token)

    update_parser = subparsers.add_parser("update", help="Check for updates")
    update_parser.add_argument("--force", action="store_true")
    update_parser.add_argument("--beta", action="store_true")
    update_parser.add_argument("--canary", action="store_true")
    update_parser.add_argument("--dry-run", action="store_true")
    update_parser.add_argument("--list-versions", action="store_true")
    update_parser.add_argument("--version")
    update_parser.add_argument("--rollback")
    update_parser.set_defaults(func=_handle_update)

    install_parser = subparsers.add_parser("install", help="Install Claude Code")
    install_parser.add_argument("target", nargs="?")
    install_parser.add_argument("--force", action="store_true")
    install_parser.set_defaults(func=_handle_install)

    github_setup_parser = subparsers.add_parser("github-setup", help="Setup GitHub Actions workflow")
    github_setup_parser.set_defaults(func=_handle_github_setup)

    review_pr_parser = subparsers.add_parser("review-pr", help="Review a GitHub pull request")
    review_pr_parser.add_argument("number")
    review_pr_parser.set_defaults(func=_handle_review_pr)

    provider_parser = subparsers.add_parser("provider", help="Show current API provider configuration")
    provider_parser.set_defaults(func=_handle_provider)

    checkpoint_parser = subparsers.add_parser("checkpoint", help="Manage file checkpoints")
    checkpoint_parser.add_argument("action", nargs="?")
    checkpoint_parser.add_argument("file", nargs="?")
    checkpoint_parser.set_defaults(func=_handle_checkpoint)

    login_parser = subparsers.add_parser("login", help="Login to Claude")
    login_parser.add_argument("--api-key", action="store_true")
    login_parser.add_argument("--oauth", action="store_true")
    login_parser.add_argument("--claudeai", action="store_true")
    login_parser.add_argument("--console", action="store_true")
    login_parser.set_defaults(func=_handle_login)

    logout_parser = subparsers.add_parser("logout", help="Logout from Claude")
    logout_parser.set_defaults(func=_handle_logout)

    api_parser = subparsers.add_parser("api", help="Interact with Claude API directly")
    api_sub = api_parser.add_subparsers(dest="api_command")

    api_query = api_sub.add_parser("query", help="Send a direct query")
    api_query.add_argument("query", nargs="+")
    api_query.add_argument("-m", "--model", default="claude-sonnet-4-20250514")
    api_query.set_defaults(func=_handle_api_query)

    api_models = api_sub.add_parser("models", help="List available models")
    api_models.set_defaults(func=_handle_api_models)

    api_test = api_sub.add_parser("test", help="Test API connection")
    api_test.set_defaults(func=_handle_api_test)

    tokens_parser = api_sub.add_parser("tokens", help="Manage API tokens")
    tokens_sub = tokens_parser.add_subparsers(dest="tokens_command")

    tokens_status = tokens_sub.add_parser("status", help="Show current token configuration")
    tokens_status.set_defaults(func=_handle_tokens_status)

    tokens_clear = tokens_sub.add_parser("clear", help="Clear stored token")
    tokens_clear.set_defaults(func=_handle_tokens_clear)

    plugin_parser = subparsers.add_parser("plugin", help="Manage Claude Code plugins")
    plugin_sub = plugin_parser.add_subparsers(dest="plugin_command")

    plugin_list = plugin_sub.add_parser("list", help="List installed plugins")
    plugin_list.add_argument("-a", "--all", action="store_true")
    plugin_list.add_argument("-v", "--verbose", action="store_true")
    plugin_list.set_defaults(func=_handle_plugin_list)

    plugin_install = plugin_sub.add_parser("install", help="Install a plugin")
    plugin_install.add_argument("plugin")
    plugin_install.set_defaults(func=_handle_plugin_install)

    plugin_remove = plugin_sub.add_parser("remove", help="Remove a plugin")
    plugin_remove.add_argument("plugin")
    plugin_remove.set_defaults(func=_handle_plugin_remove)

    plugin_enable = plugin_sub.add_parser("enable", help="Enable a plugin")
    plugin_enable.add_argument("plugin")
    plugin_enable.set_defaults(func=_handle_plugin_enable)

    plugin_disable = plugin_sub.add_parser("disable", help="Disable a plugin")
    plugin_disable.add_argument("plugin")
    plugin_disable.set_defaults(func=_handle_plugin_disable)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if getattr(args, "command", None):
        handler = getattr(args, "func", None)
        if handler:
            return handler(args)
        parser.print_help()
        return 1

    return _handle_default(args)


if __name__ == "__main__":
    raise SystemExit(main())
