"""Shared types for the Python Claude Code API surface."""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, TypedDict, Union


class ToolDefinition(TypedDict):
    name: str
    description: str
    inputSchema: Dict[str, Any]


class ToolResult(TypedDict, total=False):
    success: bool
    output: str
    error: str


class ToolUseBlock(TypedDict):
    type: Literal["tool_use"]
    id: str
    name: str
    input: Dict[str, Any]


class ToolResultBlock(TypedDict):
    type: Literal["tool_result"]
    tool_use_id: str
    content: str


class TextBlock(TypedDict):
    type: Literal["text"]
    text: str


class ImageBlock(TypedDict):
    type: Literal["image"]
    source: Dict[str, Any]


ContentBlock = Union[ToolUseBlock, ToolResultBlock, TextBlock, ImageBlock, Dict[str, Any]]


class Message(TypedDict, total=False):
    role: Literal["user", "assistant"]
    content: Union[str, List[ContentBlock]]
    id: str
    model: str
    stop_reason: Optional[str]
    usage: Dict[str, Any]


class StreamEvent(TypedDict, total=False):
    type: str
    text: str
    id: str
    name: str
    input: str
    stopReason: str
    usage: Dict[str, Any]
    error: str
