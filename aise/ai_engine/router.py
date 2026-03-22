# aise/ai_engine/router.py
"""LLM provider routing and failover logic.

This module provides the LLMRouter class that manages multiple LLM providers,
handles automatic failover, and tracks provider availability.

Example usage:
    >>> from aise.ai_engine.router import LLMRouter
    >>> from aise.core.config import get_config
    >>> 
    >>> config = get_config()
    >>> router = LLMRouter(config)
    >>> 
    >>> messages = [{"role": "user", "content": "Hello!"}]
    >>> result = await router.complete(messages)
    >>> print(result.content)
"""

from typing import List, Dict, Optional, AsyncIterator, Any
from datetime import datetime, timedelta
from enum import Enum
import structlog

from aise.ai_engine.base import LLMProvider, CompletionResult
from aise.ai_engine.anthropic_provider import AnthropicProvider
from aise.ai_engine.openai_provider import OpenAIProvider
from aise.ai_engine.deepseek_provider import DeepSeekProvider
from aise.ai_engine.local_provider import OllamaProvider
from aise.core.exceptions import ProviderError, AuthenticationError
from aise.observability.tracer import get_tracer, llm_span
from aise.observability.metrics import record_llm_call, record_llm_error

logger = structlog.get_logger(__name__)


class CircuitState(Enum):
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing — reject calls
    HALF_OPEN = "half_open"  # Testing recovery


class CircuitBreaker:
    """Circuit breaker for LLM provider calls.

    States:
        CLOSED  → normal; failures increment counter
        OPEN    → provider blocked until cooldown expires
        HALF_OPEN → one trial call allowed; success → CLOSED, failure → OPEN

    Args:
        failure_threshold: Consecutive failures before opening circuit
        cooldown_seconds: Seconds to wait before moving to HALF_OPEN
    """

    def __init__(self, failure_threshold: int = 3, cooldown_seconds: int = 300):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._opened_at: Optional[datetime] = None

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            if self._opened_at and (
                datetime.utcnow() - self._opened_at
            ).total_seconds() >= self.cooldown_seconds:
                self._state = CircuitState.HALF_OPEN
                logger.info("circuit_breaker_half_open")
        return self._state

    def is_available(self) -> bool:
        return self.state in (CircuitState.CLOSED, CircuitState.HALF_OPEN)

    def record_success(self) -> None:
        self._failure_count = 0
        self._state = CircuitState.CLOSED
        self._opened_at = None

    def record_failure(self) -> None:
        self._failure_count += 1
        if self._state == CircuitState.HALF_OPEN or self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN
            self._opened_at = datetime.utcnow()
            logger.warning(
                "circuit_breaker_opened",
                failures=self._failure_count,
                cooldown_seconds=self.cooldown_seconds,
            )


class LLMRouter:
    """Routes LLM requests to appropriate providers with automatic failover.
    
    The router maintains a priority list of providers and automatically
    fails over to the next available provider if one fails. It also
    implements a circuit breaker pattern with cooldown periods for
    failed providers.
    """
    
    def __init__(self, config):
        """Initialize LLM router with configured providers.
        
        Args:
            config: Configuration instance
        """
        self._config = config
        self._providers: Dict[str, LLMProvider] = {}
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}
        self._cooldown_minutes = 5
        self._tracer = get_tracer("aise.ai_engine.router")
        
        # Initialize providers based on configuration
        self._initialize_providers()
        
        # Set provider priority order
        self._provider_priority = self._get_provider_priority()
        
        logger.info(
            "llm_router_initialized",
            providers=list(self._providers.keys()),
            priority=self._provider_priority,
            default_provider=config.LLM_PROVIDER
        )
    
    def _initialize_providers(self):
        """Initialize available LLM providers based on configuration."""
        # Try to initialize each provider
        # Anthropic
        if self._config.ANTHROPIC_API_KEY:
            try:
                self._providers["anthropic"] = AnthropicProvider(self._config)
                logger.info("provider_initialized", provider="anthropic")
            except Exception as e:
                logger.warning("provider_init_failed", provider="anthropic", error=str(e))
        
        # OpenAI
        if self._config.OPENAI_API_KEY:
            try:
                self._providers["openai"] = OpenAIProvider(self._config)
                logger.info("provider_initialized", provider="openai")
            except Exception as e:
                logger.warning("provider_init_failed", provider="openai", error=str(e))
        
        # DeepSeek
        if self._config.DEEPSEEK_API_KEY:
            try:
                self._providers["deepseek"] = DeepSeekProvider(self._config)
                logger.info("provider_initialized", provider="deepseek")
            except Exception as e:
                logger.warning("provider_init_failed", provider="deepseek", error=str(e))
        
        # Ollama (only initialize if base URL is explicitly configured)
        if getattr(self._config, 'OLLAMA_BASE_URL', None):
            try:
                self._providers["ollama"] = OllamaProvider(self._config)
                logger.info("provider_initialized", provider="ollama")
            except Exception as e:
                logger.warning("provider_init_failed", provider="ollama", error=str(e))
        
        if not self._providers:
            raise ProviderError(
                "No LLM providers configured. "
                "Set at least one API key in .env or via 'aise config set'"
            )
    
    def _get_provider_priority(self) -> List[str]:
        """Get provider priority order based on configuration.
        
        Returns:
            List of provider names in priority order
        """
        # Start with configured default provider
        priority = []
        
        default = self._config.LLM_PROVIDER
        if default in self._providers:
            priority.append(default)
        
        # Add remaining providers in a sensible order
        fallback_order = ["anthropic", "openai", "deepseek", "ollama"]
        for provider in fallback_order:
            if provider in self._providers and provider not in priority:
                priority.append(provider)
        
        return priority
    
    def _is_provider_available(self, provider_name: str) -> bool:
        """Check if provider circuit breaker allows calls.

        Args:
            provider_name: Name of the provider

        Returns:
            True if provider is available
        """
        if provider_name not in self._circuit_breakers:
            self._circuit_breakers[provider_name] = CircuitBreaker(
                cooldown_seconds=self._cooldown_minutes * 60
            )
        return self._circuit_breakers[provider_name].is_available()

    def _mark_provider_failed(self, provider_name: str) -> None:
        """Record a provider failure in its circuit breaker.

        Args:
            provider_name: Name of the provider that failed
        """
        if provider_name not in self._circuit_breakers:
            self._circuit_breakers[provider_name] = CircuitBreaker(
                cooldown_seconds=self._cooldown_minutes * 60
            )
        self._circuit_breakers[provider_name].record_failure()
        logger.warning("provider_marked_failed", provider=provider_name)

    def _mark_provider_success(self, provider_name: str) -> None:
        """Record a provider success in its circuit breaker.

        Args:
            provider_name: Name of the provider that succeeded
        """
        if provider_name in self._circuit_breakers:
            self._circuit_breakers[provider_name].record_success()
    
    def get_provider(self, provider_name: Optional[str] = None) -> LLMProvider:
        """Get a specific provider or the default provider.
        
        Args:
            provider_name: Optional specific provider name
        
        Returns:
            LLMProvider instance
        
        Raises:
            ProviderError: If provider not found or unavailable
        """
        if provider_name:
            if provider_name not in self._providers:
                raise ProviderError(f"Provider '{provider_name}' not configured")
            return self._providers[provider_name]
        
        # Return default provider
        default = self._config.LLM_PROVIDER
        if default not in self._providers:
            # Fallback to first available provider
            if self._provider_priority:
                return self._providers[self._provider_priority[0]]
            raise ProviderError("No providers available")
        
        return self._providers[default]
    
    async def complete(
        self,
        messages: List[Dict[str, str]],
        provider: Optional[str] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
        run_metadata: Optional[Dict[str, Any]] = None,
    ) -> CompletionResult:
        """Route completion request to provider with automatic failover.
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            provider: Optional specific provider to use
            system_prompt: Optional system prompt
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            model: Specific model to use
        
        Returns:
            CompletionResult from successful provider
        
        Raises:
            ProviderError: If all providers fail
        """
        # If specific provider requested, use it without failover
        if provider:
            logger.info("routing_to_specific_provider", provider=provider)
            provider_instance = self.get_provider(provider)
            return await provider_instance.complete(
                messages=messages,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                model=model
            )
        
        # Log LangSmith metadata if present
        if run_metadata:
            logger.debug("llm_run_metadata", **run_metadata)
        
        # Try providers in priority order with failover
        last_error = None
        
        for provider_name in self._provider_priority:
            # Skip providers in cooldown
            if not self._is_provider_available(provider_name):
                logger.info(
                    "provider_skipped_cooldown",
                    provider=provider_name
                )
                continue
            
            try:
                logger.info(
                    "attempting_provider",
                    provider=provider_name,
                    attempt_number=self._provider_priority.index(provider_name) + 1
                )
                
                provider_instance = self._providers[provider_name]
                import time as _time
                _t0 = _time.monotonic()
                with llm_span(
                    self._tracer,
                    provider=provider_name,
                    model=model or "default",
                    temperature=temperature,
                ) as span:
                    result = await provider_instance.complete(
                        messages=messages,
                        system_prompt=system_prompt,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        model=model
                    )
                    span.set_attribute("llm.prompt_tokens", result.usage.prompt_tokens)
                    span.set_attribute("llm.completion_tokens", result.usage.completion_tokens)
                    span.set_attribute("llm.total_tokens", result.usage.total_tokens)
                    if result.usage.estimated_cost_usd is not None:
                        span.set_attribute("llm.cost_usd", result.usage.estimated_cost_usd)
                
                _duration = _time.monotonic() - _t0
                record_llm_call(
                    provider=provider_name,
                    model=result.model,
                    prompt_tokens=result.usage.prompt_tokens,
                    completion_tokens=result.usage.completion_tokens,
                    duration_seconds=_duration,
                    cost_usd=result.usage.estimated_cost_usd,
                )
                
                logger.info(
                    "provider_success",
                    provider=provider_name,
                    tokens=result.usage.total_tokens
                )
                
                self._mark_provider_success(provider_name)
                return result
                
            except AuthenticationError as e:
                record_llm_error(provider_name, "auth")
                logger.error(
                    "provider_auth_failed",
                    provider=provider_name,
                    error=str(e)
                )
                self._mark_provider_failed(provider_name)
                last_error = e
                continue
                
            except ProviderError as e:
                record_llm_error(provider_name, "provider_error")
                # Temporary errors, try next provider
                logger.warning(
                    "provider_failed_trying_next",
                    provider=provider_name,
                    error=str(e)
                )
                self._mark_provider_failed(provider_name)
                last_error = e
                continue
        
        # All providers failed
        logger.error(
            "all_providers_failed",
            attempted=self._provider_priority
        )
        raise ProviderError(
            f"All LLM providers failed. Last error: {str(last_error)}"
        )
    
    async def stream_complete(
        self,
        messages: List[Dict[str, str]],
        provider: Optional[str] = None,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None
    ) -> AsyncIterator[str]:
        """Route streaming completion request to provider with failover.
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            provider: Optional specific provider to use
            system_prompt: Optional system prompt
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            model: Specific model to use
        
        Yields:
            String tokens from successful provider
        
        Raises:
            ProviderError: If all providers fail
        """
        # If specific provider requested, use it without failover
        if provider:
            logger.info("routing_stream_to_specific_provider", provider=provider)
            provider_instance = self.get_provider(provider)
            async for token in provider_instance.stream_complete(
                messages=messages,
                system_prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                model=model
            ):
                yield token
            return
        
        # Try providers in priority order with failover
        last_error = None
        
        for provider_name in self._provider_priority:
            # Skip providers in cooldown
            if not self._is_provider_available(provider_name):
                logger.info(
                    "provider_skipped_cooldown",
                    provider=provider_name
                )
                continue
            
            try:
                logger.info(
                    "attempting_stream_provider",
                    provider=provider_name
                )
                
                provider_instance = self._providers[provider_name]
                async for token in provider_instance.stream_complete(
                    messages=messages,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    model=model
                ):
                    yield token
                
                logger.info("provider_stream_success", provider=provider_name)
                return
                
            except AuthenticationError as e:
                logger.error(
                    "provider_auth_failed",
                    provider=provider_name,
                    error=str(e)
                )
                self._mark_provider_failed(provider_name)
                last_error = e
                continue
                
            except ProviderError as e:
                logger.warning(
                    "provider_stream_failed_trying_next",
                    provider=provider_name,
                    error=str(e)
                )
                last_error = e
                continue
        
        # All providers failed
        logger.error(
            "all_providers_stream_failed",
            attempted=self._provider_priority
        )
        raise ProviderError(
            f"All LLM providers failed for streaming. Last error: {str(last_error)}"
        )
