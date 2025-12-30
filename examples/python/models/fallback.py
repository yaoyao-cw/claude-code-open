from __future__ import annotations

import time
from typing import Callable, Iterable, List, Optional

from .config import model_config
from .types import (
    FallbackConfig,
    FallbackCallback,
    ModelFallbackError,
    ModelSwitchEvent,
    RetryCallback,
)


DEFAULT_RETRYABLE_ERRORS = [
    "overloaded_error",
    "rate_limit_error",
    "api_error",
    "timeout",
    "ECONNRESET",
    "ETIMEDOUT",
    "ENOTFOUND",
    "capacity_exceeded",
    "model_unavailable",
]


class ModelFallback:
    def __init__(self, config: Optional[FallbackConfig] = None) -> None:
        resolved_primary = model_config.get_default_model()
        resolved_fallbacks: List[str] = []

        if config:
            resolved_primary = model_config.resolve_alias(config.primaryModel)
            resolved_fallbacks = [model_config.resolve_alias(m) for m in config.fallbackModels]

        self._config = FallbackConfig(
            primaryModel=resolved_primary,
            fallbackModels=resolved_fallbacks,
            retryableErrors=list(config.retryableErrors) if config else list(DEFAULT_RETRYABLE_ERRORS),
            maxRetries=config.maxRetries if config else 3,
            retryDelayMs=config.retryDelayMs if config else 1000,
            exponentialBackoff=config.exponentialBackoff if config else True,
        )
        self._switch_history: List[ModelSwitchEvent] = []
        self._listeners: List[Callable[[ModelSwitchEvent], None]] = []

    def set_primary_model(self, model: str) -> None:
        resolved = model_config.resolve_alias(model)
        if resolved in self._config.fallbackModels:
            raise ValueError("Primary model cannot be the same as a fallback model")
        self._config.primaryModel = resolved

    def set_fallback_models(self, models: Iterable[str]) -> None:
        resolved_models = [model_config.resolve_alias(m) for m in models]
        if self._config.primaryModel in resolved_models:
            raise ValueError("Fallback models cannot include the primary model")
        self._config.fallbackModels = resolved_models

    def add_fallback_model(self, model: str) -> None:
        resolved = model_config.resolve_alias(model)
        if resolved == self._config.primaryModel:
            raise ValueError("Fallback model cannot be the same as primary model")
        if resolved not in self._config.fallbackModels:
            self._config.fallbackModels.append(resolved)

    def get_config(self) -> FallbackConfig:
        return FallbackConfig(
            primaryModel=self._config.primaryModel,
            fallbackModels=list(self._config.fallbackModels),
            retryableErrors=list(self._config.retryableErrors),
            maxRetries=self._config.maxRetries,
            retryDelayMs=self._config.retryDelayMs,
            exponentialBackoff=self._config.exponentialBackoff,
        )

    def is_retryable(self, error: BaseException | object) -> bool:
        if not isinstance(error, BaseException):
            return False
        error_message = str(error).lower()
        error_type = ""
        if hasattr(error, "type"):
            error_type = str(getattr(error, "type")).lower()
        elif hasattr(error, "code"):
            error_type = str(getattr(error, "code")).lower()
        return any(
            retryable.lower() in error_message or retryable.lower() in error_type
            for retryable in self._config.retryableErrors
        )

    def _get_retry_delay(self, attempt: int) -> int:
        if self._config.exponentialBackoff:
            return int(self._config.retryDelayMs * (2 ** attempt))
        return self._config.retryDelayMs

    def _sleep(self, ms: int) -> None:
        time.sleep(ms / 1000)

    def execute_with_fallback(
        self,
        operation: Callable[[str], object],
        *,
        on_retry: Optional[RetryCallback] = None,
        on_fallback: Optional[FallbackCallback] = None,
    ) -> dict:
        models_to_try = [self._config.primaryModel, *self._config.fallbackModels]
        last_error: Optional[Exception] = None
        retries = 0

        for model_index, model in enumerate(models_to_try):
            for attempt in range(self._config.maxRetries + 1):
                try:
                    result = operation(model)
                    return {
                        "result": result,
                        "model": model,
                        "retries": retries,
                        "usedFallback": model_index > 0,
                    }
                except Exception as error:  # noqa: BLE001 - caller handles errors
                    last_error = error
                    retries += 1

                    if self.is_retryable(error) and attempt < self._config.maxRetries:
                        delay = self._get_retry_delay(attempt)
                        if on_retry:
                            on_retry(model, attempt + 1, error)
                        self._sleep(delay)
                        continue

                    break

            if model_index < len(models_to_try) - 1 and last_error and self.is_retryable(last_error):
                next_model = models_to_try[model_index + 1]
                if on_fallback:
                    on_fallback(model, next_model, last_error)
                self._record_switch(
                    ModelSwitchEvent(
                        fromModel=model,
                        toModel=next_model,
                        reason="fallback",
                        timestamp=int(time.time() * 1000),
                        error=str(last_error),
                    )
                )
                continue

            break

        raise ModelFallbackError(last_error or RuntimeError("Unknown error"), model, retries)

    def _record_switch(self, event: ModelSwitchEvent) -> None:
        self._switch_history.append(event)
        if len(self._switch_history) > 100:
            self._switch_history = self._switch_history[-100:]

        for listener in list(self._listeners):
            try:
                listener(event)
            except Exception:
                continue

    def get_switch_history(self) -> List[ModelSwitchEvent]:
        return list(self._switch_history)

    def on_switch(self, listener: Callable[[ModelSwitchEvent], None]) -> Callable[[], None]:
        self._listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe

    def clear_history(self) -> None:
        self._switch_history = []

    def get_stats(self) -> dict:
        switches_by_model: dict[str, int] = {}
        for event in self._switch_history:
            switches_by_model[event.fromModel] = switches_by_model.get(event.fromModel, 0) + 1

        fallback_events = [event for event in self._switch_history if event.reason == "fallback"]

        return {
            "totalSwitches": len(self._switch_history),
            "fallbackRate": (len(fallback_events) / len(self._switch_history))
            if self._switch_history
            else 0,
            "mostRecentSwitch": self._switch_history[-1] if self._switch_history else None,
            "switchesByModel": switches_by_model,
        }


model_fallback = ModelFallback()
