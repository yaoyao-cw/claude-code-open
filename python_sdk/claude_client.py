"""
Python Claude API client mirroring src/core/client.ts behavior.
"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional

import httpx
from anthropic import Anthropic


CLAUDE_CODE_BETA = "claude-code-20250219"
OAUTH_BETA = "oauth-2025-04-20"
THINKING_BETA = "interleaved-thinking-2025-05-14"

CLAUDE_CODE_IDENTITY = "You are Claude Code, Anthropic's official CLI for Claude."
CLAUDE_CODE_AGENT_SDK_IDENTITY = (
    "You are Claude Code, Anthropic's official CLI for Claude, running within the Claude Agent SDK."
)
CLAUDE_AGENT_IDENTITY = "You are a Claude agent, built on Anthropic's Claude Agent SDK."

RETRYABLE_ERRORS = [
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


@dataclass
class ProxyConfig:
    http: Optional[str] = None
    https: Optional[str] = None
    socks: Optional[str] = None
    no_proxy: Optional[str | List[str]] = None
    username: Optional[str] = None
    password: Optional[str] = None
    use_system_proxy: bool = True


@dataclass
class TimeoutConfig:
    connect: Optional[int] = None
    request: Optional[int] = None
    response: Optional[int] = None
    idle: Optional[int] = None


@dataclass
class ThinkingConfig:
    enabled: bool = False
    budget_tokens: int = 10000
    show_thinking: bool = False
    timeout: int = 120000


@dataclass
class ThinkingResult:
    thinking: str
    thinking_tokens: int
    thinking_time_ms: int
    budget_exhausted: bool


@dataclass
class ClientConfig:
    api_key: Optional[str] = None
    auth_token: Optional[str] = None
    model: Optional[str] = None
    max_tokens: Optional[int] = None
    base_url: Optional[str] = None
    max_retries: Optional[int] = None
    retry_delay: Optional[int] = None
    proxy: Optional[ProxyConfig] = None
    timeout: Optional[int | TimeoutConfig] = None
    debug: bool = False
    fallback_model: Optional[str] = None
    thinking: Optional[ThinkingConfig] = None


@dataclass
class StreamCallbacks:
    on_text: Optional[Callable[[str], None]] = None
    on_tool_use: Optional[Callable[[str, str, Any], None]] = None
    on_tool_result: Optional[Callable[[str, str], None]] = None
    on_error: Optional[Callable[[Exception], None]] = None
    on_complete: Optional[Callable[[], None]] = None


@dataclass
class UsageStats:
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost: float
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    thinking_tokens: int = 0
    api_duration_ms: int = 0


@dataclass
class ModelPricing:
    input: float
    output: float
    cache_read: float = 0.0
    cache_create: float = 0.0
    thinking: float = 0.0


@dataclass
class ModelInfo:
    model_id: str
    display_name: str
    aliases: List[str]
    context_window: int
    max_output_tokens: int
    supports_thinking: bool


@dataclass
class ModelCapabilities:
    context_window: int
    max_output_tokens: int
    supports_thinking: bool
    thinking_budget_min: Optional[int] = None
    thinking_budget_max: Optional[int] = None


@dataclass
class ModelUsageStats:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    thinking_tokens: int = 0
    cost_usd: float = 0.0
    api_calls: int = 0
    api_duration_ms: int = 0


class ModelConfig:
    def __init__(self) -> None:
        self._models: Dict[str, ModelInfo] = {}
        self._aliases: Dict[str, str] = {}
        self._pricing: Dict[str, ModelPricing] = {}
        self._initialize_models()

    def _initialize_models(self) -> None:
        models = [
            ModelInfo(
                model_id="claude-opus-4-20250514",
                display_name="Opus 4",
                aliases=["opus", "opus-4", "claude-opus-4"],
                context_window=200_000,
                max_output_tokens=32_768,
                supports_thinking=True,
            ),
            ModelInfo(
                model_id="claude-sonnet-4-20250514",
                display_name="Sonnet 4",
                aliases=["sonnet", "sonnet-4", "claude-sonnet-4"],
                context_window=200_000,
                max_output_tokens=16_384,
                supports_thinking=True,
            ),
            ModelInfo(
                model_id="claude-haiku-3-5-20241022",
                display_name="Haiku 3.5",
                aliases=["haiku", "haiku-3-5", "claude-3-5-haiku"],
                context_window=200_000,
                max_output_tokens=8_192,
                supports_thinking=False,
            ),
            ModelInfo(
                model_id="claude-3-5-sonnet-20241022",
                display_name="Sonnet 3.5",
                aliases=["sonnet-3-5", "claude-3-5-sonnet"],
                context_window=200_000,
                max_output_tokens=8_192,
                supports_thinking=False,
            ),
        ]
        pricing = {
            "claude-opus-4-20250514": ModelPricing(input=15, output=75, cache_read=1.5, cache_create=18.75, thinking=75),
            "claude-sonnet-4-20250514": ModelPricing(input=3, output=15, cache_read=0.3, cache_create=3.75, thinking=15),
            "claude-haiku-3-5-20241022": ModelPricing(input=0.8, output=4, cache_read=0.08, cache_create=1),
            "claude-3-5-sonnet-20241022": ModelPricing(input=3, output=15, cache_read=0.3, cache_create=3.75),
        }

        for model in models:
            self._models[model.model_id] = model
            for alias in model.aliases + [model.model_id]:
                self._aliases[alias.lower()] = model.model_id

        self._pricing.update(pricing)

    def resolve_alias(self, model_id_or_alias: str) -> str:
        return self._aliases.get(model_id_or_alias.lower(), model_id_or_alias)

    def get_capabilities(self, model_id_or_alias: str) -> ModelCapabilities:
        model_id = self.resolve_alias(model_id_or_alias)
        model = self._models.get(model_id)
        if not model:
            return ModelCapabilities(
                context_window=200_000,
                max_output_tokens=8192,
                supports_thinking=False,
            )
        return ModelCapabilities(
            context_window=model.context_window,
            max_output_tokens=model.max_output_tokens,
            supports_thinking=model.supports_thinking,
            thinking_budget_min=1024 if model.supports_thinking else None,
            thinking_budget_max=128_000 if model.supports_thinking else None,
        )

    def calculate_cost(
        self,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0,
        thinking_tokens: int = 0,
    ) -> float:
        pricing = self._pricing.get(self.resolve_alias(model_id))
        if not pricing:
            return 0.0
        return (
            (input_tokens / 1_000_000) * pricing.input
            + (output_tokens / 1_000_000) * pricing.output
            + (cache_read_tokens / 1_000_000) * pricing.cache_read
            + (cache_creation_tokens / 1_000_000) * pricing.cache_create
            + (thinking_tokens / 1_000_000) * pricing.thinking
        )


class ModelStats:
    def __init__(self, model_config: ModelConfig) -> None:
        self._model_config = model_config
        self._stats: Dict[str, ModelUsageStats] = {}
        self._global = ModelUsageStats()

    def record(
        self,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0,
        thinking_tokens: int = 0,
        api_duration_ms: int = 0,
    ) -> None:
        resolved = self._model_config.resolve_alias(model_id)
        stats = self._stats.setdefault(resolved, ModelUsageStats())
        cost = self._model_config.calculate_cost(
            resolved,
            input_tokens,
            output_tokens,
            cache_read_tokens,
            cache_creation_tokens,
            thinking_tokens,
        )

        stats.input_tokens += input_tokens
        stats.output_tokens += output_tokens
        stats.cache_read_tokens += cache_read_tokens
        stats.cache_creation_tokens += cache_creation_tokens
        stats.thinking_tokens += thinking_tokens
        stats.cost_usd += cost
        stats.api_calls += 1
        stats.api_duration_ms += api_duration_ms

        self._global.input_tokens += input_tokens
        self._global.output_tokens += output_tokens
        self._global.cache_read_tokens += cache_read_tokens
        self._global.cache_creation_tokens += cache_creation_tokens
        self._global.thinking_tokens += thinking_tokens
        self._global.cost_usd += cost
        self._global.api_calls += 1
        self._global.api_duration_ms += api_duration_ms

    def get_by_model(self, model_id: str) -> ModelUsageStats:
        resolved = self._model_config.resolve_alias(model_id)
        return ModelUsageStats(**self._stats.get(resolved, ModelUsageStats()).__dict__)

    def get_global(self) -> ModelUsageStats:
        return ModelUsageStats(**self._global.__dict__)


class ThinkingManager:
    def __init__(self, config: Optional[ThinkingConfig] = None) -> None:
        self._config = config or ThinkingConfig()

    def configure(self, config: ThinkingConfig) -> None:
        self._config = config

    def get_thinking_params(self, model_id: str, capabilities: ModelCapabilities) -> Dict[str, Any]:
        if not self._config.enabled or not capabilities.supports_thinking:
            return {}
        budget = self._config.budget_tokens
        if capabilities.thinking_budget_min is not None:
            budget = max(capabilities.thinking_budget_min, budget)
        if capabilities.thinking_budget_max is not None:
            budget = min(capabilities.thinking_budget_max, budget)
        return {"thinking": {"type": "enabled", "budget_tokens": budget}}

    def process_thinking_response(self, thinking: Optional[str], thinking_tokens: int, start_time: float) -> Optional[ThinkingResult]:
        if not thinking:
            return None
        thinking_time_ms = int((time.time() - start_time) * 1000)
        budget_exhausted = thinking_tokens >= int(self._config.budget_tokens * 0.95)
        return ThinkingResult(
            thinking=thinking,
            thinking_tokens=thinking_tokens,
            thinking_time_ms=thinking_time_ms,
            budget_exhausted=budget_exhausted,
        )


class ModelFallback:
    def __init__(self, primary_model: str, fallback_model: Optional[str], model_config: ModelConfig) -> None:
        self._primary = primary_model
        self._fallback = fallback_model
        self._model_config = model_config
        self._retryable_errors = RETRYABLE_ERRORS
        self._max_retries = 3
        self._retry_delay = 1000

    def execute_with_fallback(
        self,
        operation: Callable[[str], Any],
        on_retry: Optional[Callable[[str, int, Exception], None]] = None,
        on_fallback: Optional[Callable[[str, str, Exception], None]] = None,
    ) -> Dict[str, Any]:
        current_model = self._primary
        used_fallback = False
        retry_count = 0
        last_error: Optional[Exception] = None

        attempt = 0
        while attempt <= self._max_retries:
            try:
                result = operation(current_model)
                return {"result": result, "model": current_model, "retries": retry_count, "used_fallback": used_fallback}
            except Exception as exc:
                last_error = exc
                error_message = str(exc).lower()
                error_type = getattr(exc, "type", "") or getattr(exc, "code", "")
                retryable = any(
                    token in error_message or token in str(error_type).lower() for token in self._retryable_errors
                )

                if retryable and attempt < self._max_retries:
                    retry_count += 1
                    delay = self._retry_delay * (2 ** attempt)
                    if on_retry:
                        on_retry(current_model, attempt + 1, exc)
                    time.sleep(delay / 1000)
                    attempt += 1
                    continue

                if current_model == self._primary and self._fallback and retryable:
                    current_model = self._fallback
                    used_fallback = True
                    if on_fallback:
                        on_fallback(self._primary, self._fallback, exc)
                    attempt = 0
                    continue
                break

        raise last_error or RuntimeError("Unknown failure")


model_config = ModelConfig()
model_stats = ModelStats(model_config)

_session_id: Optional[str] = None
_user_id: Optional[str] = None


def _get_session_id() -> str:
    global _session_id
    if _session_id is None:
        _session_id = str(uuid.uuid4())
    return _session_id


def _get_user_id() -> str:
    global _user_id
    if _user_id is None:
        _user_id = uuid.uuid4().hex
    return _user_id


def has_valid_identity(system_prompt: Optional[str | List[Dict[str, str]]]) -> bool:
    if not system_prompt:
        return False

    if isinstance(system_prompt, str):
        return system_prompt.startswith(CLAUDE_CODE_IDENTITY) or system_prompt.startswith(
            CLAUDE_CODE_AGENT_SDK_IDENTITY
        ) or system_prompt.startswith(CLAUDE_AGENT_IDENTITY)

    if isinstance(system_prompt, list) and system_prompt:
        first_block = system_prompt[0]
        if first_block.get("type") == "text" and first_block.get("text"):
            text = first_block["text"]
            return text.startswith(CLAUDE_CODE_IDENTITY) or text.startswith(CLAUDE_CODE_AGENT_SDK_IDENTITY) or text.startswith(
                CLAUDE_AGENT_IDENTITY
            )

    return False


def format_system_prompt(system_prompt: Optional[str], is_oauth: bool) -> Optional[str | List[Dict[str, Any]]]:
    if not is_oauth:
        return system_prompt

    if not system_prompt:
        return [{"type": "text", "text": CLAUDE_CODE_IDENTITY, "cache_control": {"type": "ephemeral"}}]

    identity_to_use = CLAUDE_CODE_IDENTITY
    remaining_text = ""

    if system_prompt.startswith(CLAUDE_CODE_IDENTITY):
        identity_to_use = CLAUDE_CODE_IDENTITY
        remaining_text = system_prompt[len(CLAUDE_CODE_IDENTITY) :].strip()
    elif system_prompt.startswith(CLAUDE_CODE_AGENT_SDK_IDENTITY):
        identity_to_use = CLAUDE_CODE_AGENT_SDK_IDENTITY
        remaining_text = system_prompt[len(CLAUDE_CODE_AGENT_SDK_IDENTITY) :].strip()
    elif system_prompt.startswith(CLAUDE_AGENT_IDENTITY):
        identity_to_use = CLAUDE_AGENT_IDENTITY
        remaining_text = system_prompt[len(CLAUDE_AGENT_IDENTITY) :].strip()
    else:
        return [
            {"type": "text", "text": CLAUDE_CODE_IDENTITY, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}},
        ]

    blocks: List[Dict[str, Any]] = [
        {"type": "text", "text": identity_to_use, "cache_control": {"type": "ephemeral"}}
    ]
    if remaining_text:
        blocks.append({"type": "text", "text": remaining_text, "cache_control": {"type": "ephemeral"}})
    return blocks


class ClaudeClient:
    def __init__(self, config: Optional[ClientConfig] = None) -> None:
        config = config or ClientConfig()

        auth_token = config.auth_token or os.getenv("ANTHROPIC_AUTH_TOKEN")
        api_key = None if auth_token else (config.api_key or os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY"))

        if not api_key and not auth_token:
            print("[ClaudeClient] ERROR: No API key found!")
            print("[ClaudeClient] Please set ANTHROPIC_API_KEY environment variable or provide api_key in config")

        self._is_oauth = bool(auth_token)

        default_headers = {
            "x-app": "cli",
            "User-Agent": "claude-cli/2.0.76 (external, claude-vscode, agent-sdk/0.1.75)",
            "anthropic-dangerous-direct-browser-access": "true",
        }

        http_client = self._create_http_client(config)

        self.client = Anthropic(
            api_key=api_key,
            auth_token=auth_token,
            base_url=config.base_url,
            max_retries=0,
            default_headers=default_headers,
            http_client=http_client,
        )

        self.debug = config.debug
        resolved_model = model_config.resolve_alias(config.model or "sonnet")
        self.model = resolved_model
        capabilities = model_config.get_capabilities(self.model)
        self.max_tokens = config.max_tokens or min(32000, capabilities.max_output_tokens)
        self.max_retries = config.max_retries if config.max_retries is not None else 2
        self.retry_delay = config.retry_delay if config.retry_delay is not None else 1000
        self.fallback_model = None
        if config.fallback_model:
            resolved_fallback = model_config.resolve_alias(config.fallback_model)
            if resolved_fallback != self.model:
                self.fallback_model = resolved_fallback

        self._thinking_manager = ThinkingManager(config.thinking or ThinkingConfig())
        self._model_fallback = ModelFallback(self.model, self.fallback_model, model_config)

        self.total_usage = UsageStats(
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            estimated_cost=0.0,
            cache_read_tokens=0,
            cache_creation_tokens=0,
            thinking_tokens=0,
            api_duration_ms=0,
        )

        if self.debug:
            print(f"[ClaudeClient] Initialized with model: {self.model}")
            print(f"[ClaudeClient] Context window: {capabilities.context_window:,} tokens")
            print(f"[ClaudeClient] Supports thinking: {capabilities.supports_thinking}")
            if self.fallback_model:
                print(f"[ClaudeClient] Fallback model: {self.fallback_model}")

    def _create_http_client(self, config: ClientConfig) -> httpx.Client:
        proxies = self._build_proxies(config.proxy)
        timeout = self._build_timeout(config.timeout)
        return httpx.Client(proxies=proxies, timeout=timeout)

    def _build_proxies(self, proxy: Optional[ProxyConfig]) -> Optional[Dict[str, str]]:
        if not proxy:
            return None

        proxies: Dict[str, str] = {}
        if proxy.use_system_proxy:
            for key in ("http", "https"):
                env_value = os.getenv(f"{key}_proxy") or os.getenv(f"{key.upper()}_PROXY")
                if env_value:
                    proxies[key] = env_value

        if proxy.http:
            proxies["http"] = proxy.http
        if proxy.https:
            proxies["https"] = proxy.https
        if proxy.socks:
            proxies["all"] = proxy.socks

        if proxy.username and proxy.password:
            for key, value in list(proxies.items()):
                if "@" not in value:
                    scheme, rest = value.split("://", 1) if "://" in value else ("http", value)
                    proxies[key] = f"{scheme}://{proxy.username}:{proxy.password}@{rest}"

        return proxies or None

    def _build_timeout(self, timeout: Optional[int | TimeoutConfig]) -> Optional[httpx.Timeout]:
        if timeout is None:
            return None
        if isinstance(timeout, int):
            seconds = timeout / 1000
            return httpx.Timeout(seconds)
        return httpx.Timeout(
            connect=(timeout.connect or 30000) / 1000,
            read=(timeout.response or timeout.request or 120000) / 1000,
            write=(timeout.response or timeout.request or 120000) / 1000,
            pool=(timeout.idle or 60000) / 1000,
        )

    def _with_retry(self, operation: Callable[[], Any], retry_count: int = 0) -> Any:
        try:
            return operation()
        except Exception as exc:
            error_message = str(exc)
            error_type = getattr(exc, "type", "") or getattr(exc, "code", "")
            error_status = getattr(exc, "status", "") or getattr(exc, "status_code", "")
            is_retryable = any(
                token in error_message or token in str(error_type) for token in RETRYABLE_ERRORS
            )

            if self.debug:
                print("[ClaudeClient] API Error Details:")
                print(f"  Type: {error_type}")
                print(f"  Status: {error_status}")
                print(f"  Message: {error_message}")

            if is_retryable and retry_count < self.max_retries:
                delay = self.retry_delay * (2 ** retry_count)
                print(
                    f"[ClaudeClient] API error ({error_type}), retrying in {delay}ms... "
                    f"(attempt {retry_count + 1}/{self.max_retries})"
                )
                time.sleep(delay / 1000)
                return self._with_retry(operation, retry_count + 1)

            print(f"[ClaudeClient] API request failed: {error_message}")
            if error_status == 401:
                print("[ClaudeClient] Authentication failed - check your API key")
            elif error_status == 403:
                print("[ClaudeClient] Access denied - check API key permissions")
            elif error_status == 400:
                print("[ClaudeClient] Bad request - check your request parameters")
            raise

    def _calculate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0,
        thinking_tokens: int = 0,
    ) -> float:
        return model_config.calculate_cost(
            self.model,
            input_tokens,
            output_tokens,
            cache_read_tokens,
            cache_creation_tokens,
            thinking_tokens,
        )

    def _update_usage(
        self,
        input_tokens: int,
        output_tokens: int,
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0,
        thinking_tokens: int = 0,
        api_duration_ms: int = 0,
    ) -> None:
        self.total_usage.input_tokens += input_tokens
        self.total_usage.output_tokens += output_tokens
        self.total_usage.total_tokens += input_tokens + output_tokens
        self.total_usage.cache_read_tokens += cache_read_tokens
        self.total_usage.cache_creation_tokens += cache_creation_tokens
        self.total_usage.thinking_tokens += thinking_tokens
        self.total_usage.api_duration_ms += api_duration_ms
        self.total_usage.estimated_cost += self._calculate_cost(
            input_tokens,
            output_tokens,
            cache_read_tokens,
            cache_creation_tokens,
            thinking_tokens,
        )

        model_stats.record(
            self.model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read_tokens,
            cache_creation_tokens=cache_creation_tokens,
            thinking_tokens=thinking_tokens,
            api_duration_ms=api_duration_ms,
        )

    def _build_metadata(self) -> Dict[str, str]:
        return {"user_id": f"user_{_get_user_id()}_account__session_{_get_session_id()}"}

    def _build_betas(self, is_oauth: bool) -> List[str]:
        betas: List[str] = []
        if is_oauth:
            betas.append(CLAUDE_CODE_BETA)
            betas.append(OAUTH_BETA)
        betas.append(THINKING_BETA)
        return betas

    def create_message(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system_prompt: Optional[str] = None,
        enable_thinking: bool = False,
        thinking_budget: Optional[int] = None,
    ) -> Dict[str, Any]:
        start_time = time.time()
        capabilities = model_config.get_capabilities(self.model)
        thinking_params = self._thinking_manager.get_thinking_params(self.model, capabilities) if enable_thinking else {}
        if thinking_budget and "thinking" in thinking_params:
            thinking_params["thinking"]["budget_tokens"] = thinking_budget

        def execute_request(model: str) -> Any:
            betas = self._build_betas(self._is_oauth)
            formatted_system = format_system_prompt(system_prompt, self._is_oauth)

            request_params: Dict[str, Any] = {
                "model": model,
                "max_tokens": self.max_tokens,
                "system": formatted_system,
                "messages": [{"role": m["role"], "content": m["content"]} for m in messages],
                "metadata": self._build_metadata(),
                **thinking_params,
            }
            if tools:
                request_params["tools"] = [
                    {
                        "name": t["name"],
                        "description": t.get("description"),
                        "input_schema": t.get("input_schema") or t.get("inputSchema"),
                    }
                    for t in tools
                ]
            if betas:
                request_params["betas"] = betas

            if self.debug:
                print("[ClaudeClient] Using beta.messages.create with betas:", betas)
                print("[ClaudeClient] System prompt format:", "array" if isinstance(formatted_system, list) else "string")

            return self._with_retry(lambda: self.client.beta.messages.create(**request_params))

        if self.fallback_model:
            result = self._model_fallback.execute_with_fallback(
                execute_request,
                on_retry=lambda model, attempt, exc: self.debug
                and print(f"[ClaudeClient] Retry {attempt} for {model}: {exc}"),
                on_fallback=lambda from_model, to_model, exc: print(
                    f"[ClaudeClient] Falling back from {from_model} to {to_model}: {exc}"
                ),
            )
            response = result["result"]
            used_model = result["model"]
        else:
            response = execute_request(self.model)
            used_model = self.model

        api_duration_ms = int((time.time() - start_time) * 1000)
        usage = getattr(response, "usage", None) or {}
        input_tokens = getattr(usage, "input_tokens", usage.get("input_tokens", 0))
        output_tokens = getattr(usage, "output_tokens", usage.get("output_tokens", 0))
        cache_read_tokens = getattr(usage, "cache_read_input_tokens", usage.get("cache_read_input_tokens", 0))
        cache_creation_tokens = getattr(usage, "cache_creation_input_tokens", usage.get("cache_creation_input_tokens", 0))
        thinking_tokens = getattr(usage, "thinking_tokens", 0) or getattr(response, "thinking_tokens", 0)

        thinking_result = None
        thinking_content = getattr(response, "thinking", None)
        if thinking_content or thinking_tokens:
            thinking_result = self._thinking_manager.process_thinking_response(
                thinking_content,
                thinking_tokens,
                start_time,
            )

        self._update_usage(
            input_tokens,
            output_tokens,
            cache_read_tokens,
            cache_creation_tokens,
            thinking_tokens,
            api_duration_ms,
        )

        return {
            "content": getattr(response, "content", []),
            "stop_reason": getattr(response, "stop_reason", "end_turn"),
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cache_read_tokens": cache_read_tokens,
                "cache_creation_tokens": cache_creation_tokens,
                "thinking_tokens": thinking_tokens,
            },
            "thinking": thinking_result,
            "model": used_model,
        }

    def create_message_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        system_prompt: Optional[str] = None,
        enable_thinking: bool = False,
        thinking_budget: Optional[int] = None,
        callbacks: Optional[StreamCallbacks] = None,
    ) -> Iterable[Dict[str, Any]]:
        capabilities = model_config.get_capabilities(self.model)
        thinking_params = self._thinking_manager.get_thinking_params(self.model, capabilities) if enable_thinking else {}
        if thinking_budget and "thinking" in thinking_params:
            thinking_params["thinking"]["budget_tokens"] = thinking_budget

        betas = self._build_betas(self._is_oauth)
        formatted_system = format_system_prompt(system_prompt, self._is_oauth)

        request_params: Dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": formatted_system,
            "messages": [{"role": m["role"], "content": m["content"]} for m in messages],
            "metadata": self._build_metadata(),
            **thinking_params,
        }
        if tools:
            request_params["tools"] = [
                {
                    "name": t["name"],
                    "description": t.get("description"),
                    "input_schema": t.get("input_schema") or t.get("inputSchema"),
                }
                for t in tools
            ]
        if betas:
            request_params["betas"] = betas

        if self.debug:
            print("[ClaudeClient] Using beta.messages.stream with betas:", betas)
            print("[ClaudeClient] System prompt format:", "array" if isinstance(formatted_system, list) else "string")

        input_tokens = 0
        output_tokens = 0
        cache_read_tokens = 0
        cache_creation_tokens = 0
        thinking_tokens = 0

        try:
            with self.client.beta.messages.stream(**request_params) as stream:
                for event in stream:
                    if event.type == "content_block_delta":
                        delta = event.delta
                        if delta.type == "text_delta":
                            if callbacks and callbacks.on_text:
                                callbacks.on_text(delta.text)
                            yield {"type": "text", "text": delta.text}
                        elif delta.type == "thinking_delta":
                            yield {"type": "thinking", "thinking": delta.thinking}
                        elif delta.type == "input_json_delta":
                            yield {"type": "tool_use_delta", "input": delta.partial_json}
                    elif event.type == "content_block_start":
                        block = event.content_block
                        if block.type == "tool_use":
                            if callbacks and callbacks.on_tool_use:
                                callbacks.on_tool_use(block.id, block.name, block.input)
                            yield {"type": "tool_use_start", "id": block.id, "name": block.name}
                    elif event.type == "message_delta":
                        if event.usage:
                            output_tokens = getattr(event.usage, "output_tokens", output_tokens)
                    elif event.type == "message_start":
                        msg = event.message
                        if msg and msg.usage:
                            input_tokens = getattr(msg.usage, "input_tokens", input_tokens)
                            cache_read_tokens = getattr(msg.usage, "cache_read_input_tokens", cache_read_tokens)
                            cache_creation_tokens = getattr(msg.usage, "cache_creation_input_tokens", cache_creation_tokens)
                    elif event.type == "message_stop":
                        final_message = stream.get_final_message()
                        if final_message and final_message.usage:
                            thinking_tokens = getattr(final_message.usage, "thinking_tokens", 0)

                        self._update_usage(
                            input_tokens,
                            output_tokens,
                            cache_read_tokens,
                            cache_creation_tokens,
                            thinking_tokens,
                        )
                        yield {
                            "type": "usage",
                            "usage": {
                                "input_tokens": input_tokens,
                                "output_tokens": output_tokens,
                                "cache_read_tokens": cache_read_tokens,
                                "cache_creation_tokens": cache_creation_tokens,
                                "thinking_tokens": thinking_tokens,
                            },
                        }
                        yield {"type": "stop"}
                if callbacks and callbacks.on_complete:
                    callbacks.on_complete()
        except Exception as exc:
            if callbacks and callbacks.on_error:
                callbacks.on_error(exc)
            yield {"type": "error", "error": str(exc)}

    def get_usage_stats(self) -> UsageStats:
        return UsageStats(**self.total_usage.__dict__)

    def get_formatted_cost(self) -> str:
        if self.total_usage.estimated_cost < 0.01:
            return f"${self.total_usage.estimated_cost * 100:.2f}¢"
        return f"${self.total_usage.estimated_cost:.4f}"

    def reset_usage_stats(self) -> None:
        self.total_usage = UsageStats(
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            estimated_cost=0.0,
        )

    def set_model(self, model: str) -> None:
        self.model = model_config.resolve_alias(model)

    def get_model(self) -> str:
        return self.model

    def set_max_tokens(self, tokens: int) -> None:
        self.max_tokens = tokens

    def get_max_tokens(self) -> int:
        return self.max_tokens


__all__ = [
    "ClaudeClient",
    "ClientConfig",
    "StreamCallbacks",
    "UsageStats",
    "ThinkingConfig",
    "ThinkingResult",
    "ModelUsageStats",
    "model_stats",
    "has_valid_identity",
    "format_system_prompt",
]
