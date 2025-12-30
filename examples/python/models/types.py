from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional


@dataclass(frozen=True)
class ModelInfo:
    id: str
    displayName: str
    aliases: List[str]
    contextWindow: int
    maxOutputTokens: int
    supportsThinking: bool
    supportsTools: bool
    supportsVision: bool
    supportsPdf: bool
    supportsCaching: bool
    family: str
    releaseDate: str


@dataclass(frozen=True)
class ThinkingBudgetRange:
    min: int
    max: int
    default: int


@dataclass(frozen=True)
class ModelCapabilities:
    contextWindow: int
    maxOutputTokens: int
    supportsThinking: bool
    supportsTools: bool
    supportsVision: bool
    supportsPdf: bool
    supportsCaching: bool
    thinkingBudgetRange: Optional[ThinkingBudgetRange] = None


@dataclass(frozen=True)
class ModelPricing:
    input: float
    output: float
    cacheRead: Optional[float] = None
    cacheCreate: Optional[float] = None
    thinking: Optional[float] = None


@dataclass
class ModelUsageStats:
    inputTokens: int = 0
    outputTokens: int = 0
    cacheReadTokens: int = 0
    cacheCreationTokens: int = 0
    thinkingTokens: int = 0
    webSearchRequests: int = 0
    costUSD: float = 0.0
    contextWindowUsage: float = 0.0
    apiCalls: int = 0
    apiDurationMs: int = 0
    toolDurationMs: int = 0


@dataclass
class ThinkingConfig:
    enabled: bool = False
    budgetTokens: int = 10000
    showThinking: bool = False
    timeout: int = 120000


@dataclass
class ThinkingResult:
    thinking: str
    thinkingTokens: int
    thinkingTimeMs: int
    budgetExhausted: bool


@dataclass
class FallbackConfig:
    primaryModel: str
    fallbackModels: List[str] = field(default_factory=list)
    retryableErrors: List[str] = field(default_factory=list)
    maxRetries: int = 3
    retryDelayMs: int = 1000
    exponentialBackoff: bool = True


@dataclass
class ModelSwitchEvent:
    fromModel: str
    toModel: str
    reason: str
    timestamp: int
    error: str


class ModelFallbackError(RuntimeError):
    def __init__(self, original_error: Exception, model: Optional[str], retries: int) -> None:
        super().__init__(str(original_error))
        self.original_error = original_error
        self.model = model
        self.retries = retries


class ThinkingNotSupportedError(RuntimeError):
    def __init__(self, model_id: str) -> None:
        super().__init__(f"Extended thinking not supported for model {model_id}")
        self.model_id = model_id


RetryCallback = Callable[[str, int, Exception], None]
FallbackCallback = Callable[[str, str, Exception], None]
StatsMap = Dict[str, ModelUsageStats]
