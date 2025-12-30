from __future__ import annotations

import time
from typing import Dict, Optional

from .config import model_config
from .types import ThinkingConfig, ThinkingNotSupportedError, ThinkingResult


DEFAULT_THINKING_CONFIG = ThinkingConfig()


class ThinkingManager:
    def __init__(self, config: Optional[ThinkingConfig] = None) -> None:
        base = config if config is not None else DEFAULT_THINKING_CONFIG
        self._config = ThinkingConfig(**base.__dict__)
        self._thinking_history: list[ThinkingResult] = []

    def configure(self, config: Dict[str, object]) -> None:
        for key, value in config.items():
            if hasattr(self._config, key):
                setattr(self._config, key, value)

    def get_config(self) -> ThinkingConfig:
        return ThinkingConfig(**self._config.__dict__)

    def set_thinking_budget(self, budget: int) -> None:
        if budget < 0:
            raise ValueError("Thinking budget must be non-negative")
        self._config.budgetTokens = budget

    def get_thinking_budget(self) -> int:
        return self._config.budgetTokens or DEFAULT_THINKING_CONFIG.budgetTokens

    def is_supported(self, model_id: str) -> bool:
        return model_config.supports_extended_thinking(model_id)

    def validate_support(self, model_id: str) -> None:
        if not self.is_supported(model_id):
            raise ThinkingNotSupportedError(model_id)

    def get_thinking_params(self, model_id: str) -> Dict[str, object]:
        if not self._config.enabled:
            return {}
        if not self.is_supported(model_id):
            return {}

        capabilities = model_config.get_capabilities(model_id)
        budget_tokens = self._config.budgetTokens or DEFAULT_THINKING_CONFIG.budgetTokens

        if capabilities.thinkingBudgetRange:
            budget_tokens = max(
                capabilities.thinkingBudgetRange.min,
                min(budget_tokens, capabilities.thinkingBudgetRange.max),
            )

        return {
            "thinking": {
                "type": "enabled",
                "budget_tokens": budget_tokens,
            }
        }

    def process_thinking_response(
        self, response: Dict[str, object], start_time: int
    ) -> Optional[ThinkingResult]:
        thinking = response.get("thinking")
        if not thinking:
            return None

        result = ThinkingResult(
            thinking=str(thinking),
            thinkingTokens=int(response.get("thinking_tokens", 0)),
            thinkingTimeMs=int(time.time() * 1000) - start_time,
            budgetExhausted=False,
        )

        if self._config.budgetTokens and result.thinkingTokens >= self._config.budgetTokens * 0.95:
            result.budgetExhausted = True

        self._thinking_history.append(result)
        if len(self._thinking_history) > 50:
            self._thinking_history = self._thinking_history[-50:]

        return result

    def format_thinking(self, thinking: str, *, max_length: int = 500, show_full: bool = False) -> str:
        if not thinking:
            return ""

        show_full = show_full or self._config.showThinking
        if show_full:
            return f"<thinking>\n{thinking}\n</thinking>"

        if len(thinking) > max_length:
            truncated = thinking[:max_length]
            return (
                f"<thinking>\n{truncated}...\n"
                f"[Thinking truncated, {len(thinking)} total chars]\n</thinking>"
            )

        return f"<thinking>\n{thinking}\n</thinking>"

    def get_history(self) -> list[ThinkingResult]:
        return list(self._thinking_history)

    def clear_history(self) -> None:
        self._thinking_history = []

    def get_stats(self) -> dict:
        if not self._thinking_history:
            return {
                "totalThinking": 0,
                "totalTokens": 0,
                "totalTimeMs": 0,
                "averageTokens": 0,
                "averageTimeMs": 0,
                "budgetExhaustedCount": 0,
            }

        total_tokens = sum(r.thinkingTokens for r in self._thinking_history)
        total_time = sum(r.thinkingTimeMs for r in self._thinking_history)
        budget_exhausted = sum(1 for r in self._thinking_history if r.budgetExhausted)

        return {
            "totalThinking": len(self._thinking_history),
            "totalTokens": total_tokens,
            "totalTimeMs": total_time,
            "averageTokens": round(total_tokens / len(self._thinking_history)),
            "averageTimeMs": round(total_time / len(self._thinking_history)),
            "budgetExhaustedCount": budget_exhausted,
        }

    def recommend_budget(self, task_complexity: str) -> int:
        if task_complexity == "simple":
            return 2000
        if task_complexity == "medium":
            return 10000
        if task_complexity == "complex":
            return 50000
        return DEFAULT_THINKING_CONFIG.budgetTokens

    def enable(self, budget: Optional[int] = None) -> None:
        self._config.enabled = True
        if budget is not None:
            self._config.budgetTokens = budget

    def disable(self) -> None:
        self._config.enabled = False

    def is_enabled(self) -> bool:
        return self._config.enabled


thinking_manager = ThinkingManager()
