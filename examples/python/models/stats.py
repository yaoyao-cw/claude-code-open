from __future__ import annotations

from typing import Dict

from .config import model_config
from .types import ModelUsageStats


def create_empty_stats() -> ModelUsageStats:
    return ModelUsageStats()


class ModelStats:
    def __init__(self) -> None:
        self._stats_per_model: Dict[str, ModelUsageStats] = {}
        self._global_stats: ModelUsageStats = create_empty_stats()
        self._start_time = _now_ms()

    def record(self, model_id: str, usage: Dict[str, int]) -> None:
        resolved_model = model_config.resolve_alias(model_id)
        if resolved_model not in self._stats_per_model:
            self._stats_per_model[resolved_model] = create_empty_stats()
        model_stats = self._stats_per_model[resolved_model]

        cost = model_config.calculate_cost(
            resolved_model,
            {
                "inputTokens": usage["inputTokens"],
                "outputTokens": usage["outputTokens"],
                "cacheReadTokens": usage.get("cacheReadTokens"),
                "cacheCreationTokens": usage.get("cacheCreationTokens"),
                "thinkingTokens": usage.get("thinkingTokens"),
            },
        )

        model_stats.inputTokens += usage["inputTokens"]
        model_stats.outputTokens += usage["outputTokens"]
        model_stats.cacheReadTokens += usage.get("cacheReadTokens", 0)
        model_stats.cacheCreationTokens += usage.get("cacheCreationTokens", 0)
        model_stats.thinkingTokens += usage.get("thinkingTokens", 0)
        model_stats.webSearchRequests += usage.get("webSearchRequests", 0)
        model_stats.costUSD += cost
        model_stats.apiCalls += 1
        model_stats.apiDurationMs += usage.get("apiDurationMs", 0)
        model_stats.toolDurationMs += usage.get("toolDurationMs", 0)

        context_window = model_config.get_context_window(resolved_model)
        total_input_tokens = usage["inputTokens"] + usage.get("cacheReadTokens", 0)
        model_stats.contextWindowUsage = max(
            model_stats.contextWindowUsage,
            total_input_tokens / context_window,
        )

        self._global_stats.inputTokens += usage["inputTokens"]
        self._global_stats.outputTokens += usage["outputTokens"]
        self._global_stats.cacheReadTokens += usage.get("cacheReadTokens", 0)
        self._global_stats.cacheCreationTokens += usage.get("cacheCreationTokens", 0)
        self._global_stats.thinkingTokens += usage.get("thinkingTokens", 0)
        self._global_stats.webSearchRequests += usage.get("webSearchRequests", 0)
        self._global_stats.costUSD += cost
        self._global_stats.apiCalls += 1
        self._global_stats.apiDurationMs += usage.get("apiDurationMs", 0)
        self._global_stats.toolDurationMs += usage.get("toolDurationMs", 0)

    def get_by_model(self, model_id: str) -> ModelUsageStats:
        resolved_model = model_config.resolve_alias(model_id)
        return _clone_stats(self._stats_per_model.get(resolved_model, create_empty_stats()))

    def get_global(self) -> ModelUsageStats:
        return _clone_stats(self._global_stats)

    def get_all_by_model(self) -> Dict[str, ModelUsageStats]:
        return {model: _clone_stats(stats) for model, stats in self._stats_per_model.items()}

    def get_total_cost(self) -> float:
        return self._global_stats.costUSD

    def get_formatted_cost(self) -> str:
        cost = self._global_stats.costUSD
        if cost < 0.01:
            return f"${(cost * 100):.2f}¢"
        return f"${cost:.4f}"

    def get_total_tokens(self) -> int:
        return (
            self._global_stats.inputTokens
            + self._global_stats.outputTokens
            + self._global_stats.cacheReadTokens
            + self._global_stats.thinkingTokens
        )

    def get_session_duration(self) -> int:
        return _now_ms() - self._start_time

    def get_performance_metrics(self) -> dict:
        api_calls = self._global_stats.apiCalls
        if api_calls == 0:
            return {
                "averageApiLatency": 0,
                "averageToolLatency": 0,
                "tokensPerSecond": 0,
                "cacheHitRate": 0,
            }

        total_tokens = self._global_stats.inputTokens + self._global_stats.outputTokens
        total_api_time = self._global_stats.apiDurationMs
        total_cache_tokens = (
            self._global_stats.cacheReadTokens + self._global_stats.cacheCreationTokens
        )

        return {
            "averageApiLatency": round(total_api_time / api_calls),
            "averageToolLatency": round(self._global_stats.toolDurationMs / api_calls),
            "tokensPerSecond": round((total_tokens / total_api_time) * 1000)
            if total_api_time > 0
            else 0,
            "cacheHitRate": self._global_stats.cacheReadTokens / total_cache_tokens
            if total_cache_tokens > 0
            else 0,
        }

    def get_model_distribution(self) -> list[dict]:
        total_tokens = self.get_total_tokens()
        result: list[dict] = []
        for model, stats in self._stats_per_model.items():
            model_tokens = stats.inputTokens + stats.outputTokens + stats.cacheReadTokens
            result.append(
                {
                    "model": model,
                    "displayName": model_config.get_display_name(model),
                    "percentage": (model_tokens / total_tokens) * 100 if total_tokens > 0 else 0,
                    "tokens": model_tokens,
                    "cost": stats.costUSD,
                    "calls": stats.apiCalls,
                }
            )

        return sorted(result, key=lambda item: item["tokens"], reverse=True)

    def get_summary(self) -> str:
        lines = [
            "=== Usage Summary ===",
            f"Total Cost: {self.get_formatted_cost()}",
            f"Total Tokens: {self.get_total_tokens():,}",
            f"API Calls: {self._global_stats.apiCalls}",
            f"Session Duration: {round(self.get_session_duration() / 1000 / 60)} minutes",
        ]

        perf = self.get_performance_metrics()
        lines.append(f"Average API Latency: {perf['averageApiLatency']}ms")
        lines.append(f"Tokens/Second: {perf['tokensPerSecond']}")
        lines.append(f"Cache Hit Rate: {perf['cacheHitRate'] * 100:.1f}%")

        if len(self._stats_per_model) > 1:
            lines.append("")
            lines.append("By Model:")
            for item in self.get_model_distribution():
                lines.append(
                    f"  {item['displayName']}: {item['percentage']:.1f}% "
                    f"({item['tokens']:,} tokens, {item['calls']} calls)"
                )

        lines.append("=====================")
        return "\n".join(lines)

    def reset(self) -> None:
        self._stats_per_model.clear()
        self._global_stats = create_empty_stats()
        self._start_time = _now_ms()

    def export(self) -> dict:
        return {
            "global": _clone_stats(self._global_stats),
            "byModel": {model: _clone_stats(stats) for model, stats in self._stats_per_model.items()},
            "startTime": self._start_time,
            "duration": self.get_session_duration(),
        }


model_stats = ModelStats()


def _clone_stats(stats: ModelUsageStats) -> ModelUsageStats:
    return ModelUsageStats(**stats.__dict__)


def _now_ms() -> int:
    return int(__import__("time").time() * 1000)
