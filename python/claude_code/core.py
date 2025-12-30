from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .session import Session, session_manager


@dataclass
class MessageResponse:
    content: str
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    stop_reason: str | None = None


class ClaudeClient:
    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key
        self._anthropic = None
        try:
            import anthropic  # type: ignore

            self._anthropic = anthropic
        except ImportError:
            self._anthropic = None

    def send_message(
        self,
        prompt: str,
        *,
        model: str,
        max_tokens: int,
        system_prompt: str | None = None,
    ) -> MessageResponse:
        if self._anthropic and self.api_key:
            client = self._anthropic.Anthropic(api_key=self.api_key)
            payload: dict[str, Any] = {
                "model": model,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            }
            if system_prompt:
                payload["system"] = system_prompt
            response = client.messages.create(**payload)
            content_blocks = response.content
            text_content = ""
            for block in content_blocks:
                if getattr(block, "type", None) == "text":
                    text_content = getattr(block, "text", "")
                    break
            return MessageResponse(
                content=text_content or "[no text response]",
                model=response.model,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                stop_reason=response.stop_reason,
            )
        return MessageResponse(content=f"[stub] {prompt}", model=model, stop_reason="stub")


class ConversationLoop:
    def __init__(self, session: Session, client: ClaudeClient) -> None:
        self.session = session
        self.client = client

    def process_message(
        self,
        message: str,
        *,
        model: str,
        max_tokens: int,
        system_prompt: str | None = None,
    ) -> MessageResponse:
        self.session.add_message("user", message)
        response = self.client.send_message(
            message,
            model=model,
            max_tokens=max_tokens,
            system_prompt=system_prompt,
        )
        self.session.add_message("assistant", response.content)
        session_manager.save_session(self.session)
        return response


def start_session(working_directory: str) -> Session:
    return session_manager.create_session(working_directory=working_directory)
