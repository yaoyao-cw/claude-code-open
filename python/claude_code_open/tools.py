"""Tool registry and protocol helpers for the Python Claude Code API surface."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional

from .types import ToolDefinition, ToolResult, ToolResultBlock, ToolUseBlock, StreamEvent


PermissionBehavior = str  # 'allow' | 'deny' | 'ask'


@dataclass
class PermissionCheckResult:
    behavior: PermissionBehavior
    message: Optional[str] = None
    updated_input: Optional[Dict[str, Any]] = None


@dataclass
class ToolOptions:
    max_retries: int = 0
    base_timeout_ms: int = 120_000


class BaseTool:
    name: str
    description: str

    def __init__(self, options: Optional[ToolOptions] = None) -> None:
        self.options = options or ToolOptions()

    def get_input_schema(self) -> Dict[str, Any]:
        raise NotImplementedError

    async def execute(self, input: Dict[str, Any]) -> ToolResult:
        raise NotImplementedError

    async def check_permissions(self, input: Dict[str, Any]) -> PermissionCheckResult:
        return PermissionCheckResult(behavior="allow", updated_input=input)

    def get_definition(self) -> ToolDefinition:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.get_input_schema(),
        }

    @staticmethod
    def success(output: str) -> ToolResult:
        return {"success": True, "output": output}

    @staticmethod
    def error(message: str) -> ToolResult:
        return {"success": False, "error": message}


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[BaseTool]:
        return self._tools.get(name)

    def get_all(self) -> List[BaseTool]:
        return list(self._tools.values())

    def get_definitions(self) -> List[ToolDefinition]:
        return [tool.get_definition() for tool in self.get_all()]

    async def execute(
        self,
        name: str,
        input: Dict[str, Any],
        on_permission_request: Optional[
            Callable[[str, Dict[str, Any], Optional[str]], Awaitable[bool]]
        ] = None,
    ) -> ToolResult:
        tool = self.get(name)
        if not tool:
            return {"success": False, "error": f"Tool '{name}' not found"}

        try:
            perm_result = await tool.check_permissions(input)
            if perm_result.behavior == "deny":
                return {
                    "success": False,
                    "error": perm_result.message or "Permission denied by tool permission check",
                }

            if perm_result.behavior == "ask":
                if not on_permission_request:
                    return {
                        "success": False,
                        "error": perm_result.message
                        or "Permission required but no permission handler available",
                    }
                approved = await on_permission_request(name, input, perm_result.message)
                if not approved:
                    return {"success": False, "error": "Permission denied by user"}

            final_input = (
                perm_result.updated_input
                if perm_result.updated_input is not None
                else input
            )
            return await tool.execute(final_input)
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "error": str(exc)}


def format_tool_result(result: ToolResult) -> str:
    if result.get("success"):
        return result.get("output") or "Success (no output)"
    return f"Error: {result.get('error') or 'Unknown error'}"


class ToolStreamProcessor:
    """Collect tool_use deltas from a Client stream and execute tools."""

    def __init__(
        self,
        registry: ToolRegistry,
        tool_result_formatter: Optional[Callable[[ToolResult], str]] = None,
    ) -> None:
        self._registry = registry
        self._tool_result_formatter = tool_result_formatter or format_tool_result

    async def process_stream(
        self,
        stream: Iterable[StreamEvent] | Any,
        on_tool_start: Optional[Callable[[str, Optional[Dict[str, Any]]], Awaitable[None]]] = None,
        on_tool_end: Optional[
            Callable[[str, Dict[str, Any], ToolResult], Awaitable[None]]
        ] = None,
        on_permission_request: Optional[
            Callable[[str, Dict[str, Any], Optional[str]], Awaitable[bool]]
        ] = None,
    ) -> tuple[List[ToolUseBlock], List[ToolResultBlock]]:
        tool_calls: Dict[str, Dict[str, Any]] = {}
        current_tool_id: Optional[str] = None

        async for event in _ensure_async_iter(stream):
            event_type = event.get("type")
            if event_type == "tool_use_start":
                current_tool_id = event.get("id") or ""
                tool_calls[current_tool_id] = {
                    "name": event.get("name") or "",
                    "input": "",
                }
                if on_tool_start:
                    await on_tool_start(event.get("name") or "", None)
            elif event_type == "tool_use_delta":
                tool_id = event.get("id") or current_tool_id or ""
                if tool_id not in tool_calls:
                    tool_calls[tool_id] = {"name": "", "input": ""}
                tool_calls[tool_id]["input"] += event.get("input") or ""

        tool_use_blocks: List[ToolUseBlock] = []
        tool_result_blocks: List[ToolResultBlock] = []

        for tool_id, tool_call in tool_calls.items():
            tool_name = tool_call.get("name", "")
            raw_input = tool_call.get("input", "")
            try:
                parsed_input = json.loads(raw_input or "{}")
            except json.JSONDecodeError as exc:
                result: ToolResult = {"success": False, "error": f"Parse error: {exc}"}
                if on_tool_end:
                    await on_tool_end(tool_name, {}, result)
                tool_result_blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": self._tool_result_formatter(result),
                    }
                )
                continue

            result = await self._registry.execute(
                tool_name, parsed_input, on_permission_request
            )
            if on_tool_end:
                await on_tool_end(tool_name, parsed_input, result)

            tool_use_blocks.append(
                {
                    "type": "tool_use",
                    "id": tool_id,
                    "name": tool_name,
                    "input": parsed_input,
                }
            )
            tool_result_blocks.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": self._tool_result_formatter(result),
                }
            )

        return tool_use_blocks, tool_result_blocks


async def _ensure_async_iter(stream: Iterable[StreamEvent] | Any) -> Any:
    if hasattr(stream, "__aiter__"):
        async for item in stream:
            yield item
        return

    for item in stream:
        yield item
        await asyncio.sleep(0)
