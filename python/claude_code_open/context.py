"""Context manager for Python Claude Code API surface."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .types import ContentBlock, Message


CHARS_PER_TOKEN = 3.5
MAX_CONTEXT_TOKENS = 180000
RESERVE_TOKENS = 32000
CODE_BLOCK_MAX_LINES = 50
TOOL_OUTPUT_MAX_CHARS = 2000
SUMMARY_TARGET_RATIO = 0.3


@dataclass
class ContextConfig:
    max_tokens: int = MAX_CONTEXT_TOKENS
    reserve_tokens: int = RESERVE_TOKENS
    summarize_threshold: float = 0.7
    keep_recent_messages: int = 10
    enable_ai_summary: bool = False
    code_block_max_lines: int = CODE_BLOCK_MAX_LINES
    tool_output_max_chars: int = TOOL_OUTPUT_MAX_CHARS
    enable_incremental_compression: bool = True


@dataclass
class TokenUsage:
    input_tokens: int
    output_tokens: int
    cache_read_tokens: Optional[int] = None
    cache_creation_tokens: Optional[int] = None
    thinking_tokens: Optional[int] = None


@dataclass
class ConversationTurn:
    user: Message
    assistant: Message
    timestamp: int
    token_estimate: int
    original_tokens: int
    summarized: bool = False
    summary: Optional[str] = None
    compressed: bool = False
    api_usage: Optional[TokenUsage] = None


@dataclass
class ContextStats:
    total_messages: int
    estimated_tokens: int
    summarized_messages: int
    compression_ratio: float
    saved_tokens: int
    compression_count: int


def estimate_tokens(text: str) -> int:
    if not text:
        return 0

    has_asian = any(
        "\u4e00" <= char <= "\u9fff" or "\u3040" <= char <= "\u30ff"
        for char in text
    )
    has_code = text.lstrip().startswith("```") or any(
        token in text for token in ("function ", "class ", "const ", "let ", "var ", "import ", "export ")
    )

    chars_per_token = 2.0 if has_asian else 3.0 if has_code else CHARS_PER_TOKEN
    tokens = len(text) / chars_per_token

    special_chars = sum(1 for char in text if char in "{}[]().,;:!?<>")
    tokens += special_chars * 0.1
    tokens += text.count("\n") * 0.5

    return int(tokens) + (1 if tokens % 1 else 0)


def estimate_message_tokens(message: Message) -> int:
    content = message.get("content", "")
    if isinstance(content, str):
        return estimate_tokens(content) + 10

    total = 10
    for block in content:
        block_type = block.get("type")
        if block_type == "text":
            total += estimate_tokens(block.get("text", ""))
        elif block_type == "tool_use":
            total += estimate_tokens(block.get("name", ""))
            total += estimate_tokens(str(block.get("input", {})))
        elif block_type == "tool_result":
            tool_content = block.get("content", "")
            total += estimate_tokens(str(tool_content))
        elif block_type == "image":
            total += 1000
    return total


def estimate_total_tokens(messages: List[Message]) -> int:
    return sum(estimate_message_tokens(msg) for msg in messages)


def compress_code_block(code: str, max_lines: int) -> str:
    lines = code.split("\n")
    if len(lines) <= max_lines:
        return code
    keep_head = int(max_lines * 0.6)
    keep_tail = max_lines - keep_head
    head = "\n".join(lines[:keep_head])
    tail = "\n".join(lines[-keep_tail:])
    omitted = len(lines) - max_lines
    return f"{head}\n\n... [{omitted} lines omitted] ...\n\n{tail}"


def compress_tool_output(content: str, max_chars: int) -> str:
    if len(content) <= max_chars:
        return content

    lines = content.split("\n")
    keep_head = int(max_chars * 0.7)
    keep_tail = max_chars - keep_head
    head = content[:keep_head]
    tail = content[-keep_tail:]
    omitted = len(content) - max_chars
    return f"{head}\n... [{omitted} chars omitted] ...\n{tail}"


def compress_message(message: Message, config: ContextConfig) -> Message:
    content = message.get("content")
    if not isinstance(content, list):
        return message

    updated: List[ContentBlock] = []
    for block in content:
        if block.get("type") == "tool_result" and isinstance(block.get("content"), str):
            updated.append(
                {
                    **block,
                    "content": compress_tool_output(
                        block.get("content", ""),
                        config.tool_output_max_chars,
                    ),
                }
            )
        else:
            updated.append(block)

    return {**message, "content": updated}


def create_summary(turns: List[ConversationTurn]) -> str:
    lines: List[str] = []
    for turn in turns:
        user_text = _message_to_text(turn.user)
        assistant_text = _message_to_text(turn.assistant)
        lines.append(f"User: {user_text}")
        lines.append(f"Assistant: {assistant_text}")
    return "\n".join(lines)


def _message_to_text(message: Message) -> str:
    content = message.get("content", "")
    if isinstance(content, str):
        return content
    parts: List[str] = []
    for block in content:
        if block.get("type") == "text":
            parts.append(block.get("text", ""))
        elif block.get("type") == "tool_result":
            parts.append(str(block.get("content", "")))
    return " ".join(parts)


class ContextManager:
    def __init__(self, config: Optional[ContextConfig] = None) -> None:
        self.config = config or ContextConfig()
        self.turns: List[ConversationTurn] = []
        self.system_prompt: str = ""
        self.compression_count = 0
        self.saved_tokens = 0
        self.api_client: Optional[Any] = None

    def set_api_client(self, client: Any) -> None:
        self.api_client = client

    def set_system_prompt(self, prompt: str) -> None:
        self.system_prompt = prompt

    def add_turn(self, user: Message, assistant: Message, api_usage: Optional[TokenUsage] = None) -> None:
        original_user_tokens = estimate_message_tokens(user)
        original_assistant_tokens = estimate_message_tokens(assistant)
        original_tokens = original_user_tokens + original_assistant_tokens

        processed_user = user
        processed_assistant = assistant
        compressed = False

        if self.config.enable_incremental_compression:
            processed_user = compress_message(user, self.config)
            processed_assistant = compress_message(assistant, self.config)
            compressed_tokens = estimate_message_tokens(processed_user) + estimate_message_tokens(processed_assistant)
            if compressed_tokens < original_tokens:
                compressed = True
                self.saved_tokens += original_tokens - compressed_tokens

        token_estimate = estimate_message_tokens(processed_user) + estimate_message_tokens(processed_assistant)

        self.turns.append(
            ConversationTurn(
                user=processed_user,
                assistant=processed_assistant,
                timestamp=_timestamp_ms(),
                token_estimate=token_estimate,
                original_tokens=original_tokens,
                compressed=compressed,
                api_usage=api_usage,
            )
        )
        self._maybe_compress()

    def get_messages(self) -> List[Message]:
        messages: List[Message] = []
        summarized_turns = [turn for turn in self.turns if turn.summarized]
        if summarized_turns:
            summary = create_summary(summarized_turns)
            messages.append({"role": "user", "content": summary})
            messages.append({"role": "assistant", "content": "I understand. I'll keep this context in mind."})

        for turn in [t for t in self.turns if not t.summarized]:
            messages.append(turn.user)
            messages.append(turn.assistant)

        return messages

    def get_available_tokens(self) -> int:
        used = self.get_used_tokens()
        return self.config.max_tokens - self.config.reserve_tokens - used

    def get_used_tokens(self) -> int:
        total = estimate_tokens(self.system_prompt)
        for turn in self.turns:
            if turn.summarized and turn.summary:
                total += estimate_tokens(turn.summary)
            elif turn.api_usage:
                total += (
                    turn.api_usage.input_tokens
                    + (turn.api_usage.cache_creation_tokens or 0)
                    + (turn.api_usage.cache_read_tokens or 0)
                    + turn.api_usage.output_tokens
                    + (turn.api_usage.thinking_tokens or 0)
                )
            else:
                total += turn.token_estimate
        return total

    def compact(self) -> None:
        self._compress(force=True)

    def get_stats(self) -> ContextStats:
        summarized = sum(1 for turn in self.turns if turn.summarized)
        original_tokens = sum(turn.original_tokens for turn in self.turns)
        current_tokens = self.get_used_tokens()
        return ContextStats(
            total_messages=len(self.turns) * 2,
            estimated_tokens=current_tokens,
            summarized_messages=summarized * 2,
            compression_ratio=current_tokens / original_tokens if original_tokens else 1.0,
            saved_tokens=self.saved_tokens,
            compression_count=self.compression_count,
        )

    def reset(self) -> None:
        self.turns.clear()
        self.compression_count = 0
        self.saved_tokens = 0

    def _maybe_compress(self) -> None:
        threshold = int(self.config.max_tokens * self.config.summarize_threshold)
        if self.get_used_tokens() < threshold:
            return
        self._compress(force=False)

    def _compress(self, force: bool) -> None:
        recent_count = self.config.keep_recent_messages
        if len(self.turns) <= recent_count:
            return

        to_summarize = self.turns[:-recent_count]
        if not to_summarize:
            return

        before_tokens = sum(turn.token_estimate for turn in to_summarize)
        summary = create_summary(to_summarize)

        for turn in to_summarize:
            if not turn.summarized:
                turn.summarized = True
                turn.summary = summary

        after_tokens = estimate_tokens(summary)
        self.saved_tokens += max(0, before_tokens - after_tokens)
        self.compression_count += 1


def _timestamp_ms() -> int:
    import time

    return int(time.time() * 1000)
