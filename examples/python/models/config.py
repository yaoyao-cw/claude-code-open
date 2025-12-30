from __future__ import annotations

import re
from typing import Dict, List, Optional

from .types import ModelCapabilities, ModelInfo, ModelPricing, ThinkingBudgetRange


KNOWN_MODELS: List[ModelInfo] = [
    ModelInfo(
        id="claude-opus-4-5-20251101",
        displayName="Opus 4.5",
        aliases=["opus", "opus-4-5", "claude-opus-4-5"],
        contextWindow=1_000_000,
        maxOutputTokens=32768,
        supportsThinking=True,
        supportsTools=True,
        supportsVision=True,
        supportsPdf=True,
        supportsCaching=True,
        family="opus",
        releaseDate="2025-11-01",
    ),
    ModelInfo(
        id="claude-sonnet-4-5-20250929",
        displayName="Sonnet 4.5",
        aliases=["sonnet", "sonnet-4-5", "claude-sonnet-4-5"],
        contextWindow=1_000_000,
        maxOutputTokens=16384,
        supportsThinking=True,
        supportsTools=True,
        supportsVision=True,
        supportsPdf=True,
        supportsCaching=True,
        family="sonnet",
        releaseDate="2025-09-29",
    ),
    ModelInfo(
        id="claude-haiku-4-5-20251001",
        displayName="Haiku 4.5",
        aliases=["haiku", "haiku-4-5", "claude-haiku-4-5"],
        contextWindow=200_000,
        maxOutputTokens=8192,
        supportsThinking=False,
        supportsTools=True,
        supportsVision=True,
        supportsPdf=True,
        supportsCaching=True,
        family="haiku",
        releaseDate="2025-10-01",
    ),
    ModelInfo(
        id="claude-opus-4-20250514",
        displayName="Opus 4",
        aliases=["opus-4", "claude-opus-4"],
        contextWindow=200_000,
        maxOutputTokens=32768,
        supportsThinking=True,
        supportsTools=True,
        supportsVision=True,
        supportsPdf=True,
        supportsCaching=True,
        family="opus",
        releaseDate="2025-05-14",
    ),
    ModelInfo(
        id="claude-sonnet-4-20250514",
        displayName="Sonnet 4",
        aliases=["sonnet-4", "claude-sonnet-4"],
        contextWindow=200_000,
        maxOutputTokens=16384,
        supportsThinking=True,
        supportsTools=True,
        supportsVision=True,
        supportsPdf=True,
        supportsCaching=True,
        family="sonnet",
        releaseDate="2025-05-14",
    ),
    ModelInfo(
        id="claude-3-5-sonnet-20241022",
        displayName="Sonnet 3.5",
        aliases=["sonnet-3-5", "claude-3-5-sonnet"],
        contextWindow=200_000,
        maxOutputTokens=8192,
        supportsThinking=False,
        supportsTools=True,
        supportsVision=True,
        supportsPdf=False,
        supportsCaching=True,
        family="sonnet",
        releaseDate="2024-10-22",
    ),
    ModelInfo(
        id="claude-3-5-haiku-20241022",
        displayName="Haiku 3.5",
        aliases=["haiku-3-5", "claude-3-5-haiku"],
        contextWindow=200_000,
        maxOutputTokens=8192,
        supportsThinking=False,
        supportsTools=True,
        supportsVision=True,
        supportsPdf=False,
        supportsCaching=True,
        family="haiku",
        releaseDate="2024-10-22",
    ),
]


MODEL_PRICING: Dict[str, ModelPricing] = {
    "claude-opus-4-5-20251101": ModelPricing(
        input=15,
        output=75,
        cacheRead=1.5,
        cacheCreate=18.75,
        thinking=75,
    ),
    "claude-sonnet-4-5-20250929": ModelPricing(
        input=3,
        output=15,
        cacheRead=0.3,
        cacheCreate=3.75,
        thinking=15,
    ),
    "claude-haiku-4-5-20251001": ModelPricing(
        input=0.8,
        output=4,
        cacheRead=0.08,
        cacheCreate=1,
    ),
    "claude-opus-4-20250514": ModelPricing(
        input=15,
        output=75,
        cacheRead=1.5,
        cacheCreate=18.75,
        thinking=75,
    ),
    "claude-sonnet-4-20250514": ModelPricing(
        input=3,
        output=15,
        cacheRead=0.3,
        cacheCreate=3.75,
        thinking=15,
    ),
    "claude-3-5-sonnet-20241022": ModelPricing(
        input=3,
        output=15,
        cacheRead=0.3,
        cacheCreate=3.75,
    ),
    "claude-3-5-haiku-20241022": ModelPricing(
        input=0.8,
        output=4,
        cacheRead=0.08,
        cacheCreate=1,
    ),
}


class ModelConfig:
    def __init__(self) -> None:
        self._models: Dict[str, ModelInfo] = {}
        self._alias_map: Dict[str, str] = {}
        self._pricing: Dict[str, ModelPricing] = {}
        self._initialize_models()

    def _initialize_models(self) -> None:
        for model in KNOWN_MODELS:
            self._models[model.id] = model
            for alias in model.aliases:
                self._alias_map[alias.lower()] = model.id
            self._alias_map[model.id.lower()] = model.id

        self._pricing = dict(MODEL_PRICING)

    def resolve_alias(self, model_id_or_alias: str) -> str:
        normalized = model_id_or_alias.lower().strip()
        return self._alias_map.get(normalized, model_id_or_alias)

    def get_model_info(self, model_id_or_alias: str) -> Optional[ModelInfo]:
        model_id = self.resolve_alias(model_id_or_alias)
        return self._models.get(model_id)

    def get_capabilities(self, model_id_or_alias: str) -> ModelCapabilities:
        info = self.get_model_info(model_id_or_alias)
        if info:
            return ModelCapabilities(
                contextWindow=info.contextWindow,
                maxOutputTokens=info.maxOutputTokens,
                supportsThinking=info.supportsThinking,
                supportsTools=info.supportsTools,
                supportsVision=info.supportsVision,
                supportsPdf=info.supportsPdf,
                supportsCaching=info.supportsCaching,
                thinkingBudgetRange=ThinkingBudgetRange(min=1024, max=128000, default=10000)
                if info.supportsThinking
                else None,
            )
        return self._infer_capabilities(model_id_or_alias)

    def _infer_capabilities(self, model_id: str) -> ModelCapabilities:
        normalized = model_id.lower()

        if "[1m]" in normalized or "opus-4-5" in normalized or "sonnet-4-5" in normalized:
            return ModelCapabilities(
                contextWindow=1_000_000,
                maxOutputTokens=32768,
                supportsThinking=True,
                supportsTools=True,
                supportsVision=True,
                supportsPdf=True,
                supportsCaching=True,
                thinkingBudgetRange=ThinkingBudgetRange(min=1024, max=128000, default=10000),
            )

        supports_thinking = (
            "opus-4" in normalized
            or "sonnet-4-5" in normalized
            or "sonnet-4" in normalized
        )

        context_window = 1_000_000 if "[1m]" in normalized else 200_000

        return ModelCapabilities(
            contextWindow=context_window,
            maxOutputTokens=8192,
            supportsThinking=supports_thinking,
            supportsTools=True,
            supportsVision=True,
            supportsPdf="4" in normalized,
            supportsCaching=True,
            thinkingBudgetRange=ThinkingBudgetRange(min=1024, max=128000, default=10000)
            if supports_thinking
            else None,
        )

    def get_context_window(self, model_id_or_alias: str) -> int:
        return self.get_capabilities(model_id_or_alias).contextWindow

    def supports_extended_thinking(self, model_id_or_alias: str) -> bool:
        return self.get_capabilities(model_id_or_alias).supportsThinking

    def get_pricing(self, model_id_or_alias: str) -> ModelPricing:
        model_id = self.resolve_alias(model_id_or_alias)
        pricing = self._pricing.get(model_id)
        if pricing:
            return pricing

        info = self.get_model_info(model_id_or_alias)
        if info:
            if info.family == "opus":
                return ModelPricing(input=15, output=75)
            if info.family == "sonnet":
                return ModelPricing(input=3, output=15)
            if info.family == "haiku":
                return ModelPricing(input=0.8, output=4)

        return ModelPricing(input=3, output=15)

    def calculate_cost(
        self,
        model_id_or_alias: str,
        usage: Dict[str, int],
    ) -> float:
        pricing = self.get_pricing(model_id_or_alias)
        cost = 0.0
        cost += (usage["inputTokens"] / 1_000_000) * pricing.input
        cost += (usage["outputTokens"] / 1_000_000) * pricing.output

        cache_read = usage.get("cacheReadTokens")
        if cache_read and pricing.cacheRead:
            cost += (cache_read / 1_000_000) * pricing.cacheRead

        cache_create = usage.get("cacheCreationTokens")
        if cache_create and pricing.cacheCreate:
            cost += (cache_create / 1_000_000) * pricing.cacheCreate

        thinking_tokens = usage.get("thinkingTokens")
        if thinking_tokens and pricing.thinking:
            cost += (thinking_tokens / 1_000_000) * pricing.thinking

        return cost

    def get_all_models(self) -> List[ModelInfo]:
        return list(self._models.values())

    def get_default_model(self) -> str:
        return "claude-sonnet-4-5-20250929"

    def get_display_name(self, model_id_or_alias: str) -> str:
        info = self.get_model_info(model_id_or_alias)
        return info.displayName if info else model_id_or_alias

    def is_valid_model(self, model_id_or_alias: str) -> bool:
        resolved = self.resolve_alias(model_id_or_alias)
        return resolved in self._models or self._is_valid_model_format(resolved)

    def _is_valid_model_format(self, model_id: str) -> bool:
        return re.match(r"^claude-[\w-]+(-\d{8})?$", model_id) is not None

    def recommend_model(self, task: str) -> str:
        if task == "simple":
            return "claude-haiku-4-5-20251001"
        if task == "medium":
            return "claude-sonnet-4-5-20250929"
        if task == "complex" or task == "thinking":
            return "claude-opus-4-5-20251101"
        return self.get_default_model()


model_config = ModelConfig()
