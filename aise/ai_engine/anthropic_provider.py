# aise/ai_engine/anthropic_provider.py
"""Anthropic Claude LLM provider implementation.

This module implements the LLMProvider interface for Anthropic's Claude models,
supporting both streaming and non-streaming completions with retry logic.

Example usage:
    >>> from aise.ai_engine.anthropic_provider import AnthropicProvider
    >>> from aise.core.config import get_config
    >>> 
    >>> config = get_config()
    >>> provider = AnthropicProvider(config)
    >>> 
    >>> messages = [{"role": "user", "content": "Explain EC2 instances"}]
    >>> result = await provider.complete(messages)
    >>> print(result.content)
"""

from typing import List, Dict, Optional, AsyncIterator
import anthropic
import structlog
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type
)

from aise.ai_engine.base import LLMProvider, CompletionResult, TokenUsage
from aise.core.exceptions import ProviderError, AuthenticationError

logger = structlog.get_logger(__name__)


# Anthropic pricing per 1M tokens (update as Anthropic publishes new rates)
ANTHROPIC_PRICING = {
    # Claude 3 family
    "claude-3-opus-20240229": {"input": 15.00, "output": 75.00},
    "claude-3-sonnet-20240229": {"input": 3.00, "output": 15.00},
    "claude-3-haiku-20240307": {"input": 0.25, "output": 1.25},
    # Claude 3.5 family
    "claude-3-5-sonnet-20240620": {"input": 3.00, "output": 15.00},
    "claude-3-5-sonnet-20241022": {"input": 3.00, "output": 15.00},
    "claude-3-5-haiku-20241022": {"input": 0.80, "output": 4.00},
    # Claude 3.7 family
    "claude-3-7-sonnet-20250219": {"input": 3.00, "output": 15.00},
    # Claude 2 family
    "claude-2.1": {"input": 8.00, "output": 24.00},
    "claude-2.0": {"input": 8.00, "output": 24.00},
}

# Default fallback pricing used when a model is not in the table above.
# Matches Claude 3 Sonnet as a conservative mid-range estimate.
_DEFAULT_PRICING = {"input": 3.00, "output": 15.00}


class AnthropicProvider(LLMProvider):
    """Anthropic Claude provider implementation.
    
    Supports Claude 3 (Opus, Sonnet, Haiku) and Claude 2 models with
    streaming, retry logic, and cost tracking.
    """
    
    def __init__(self, config):
        """Initialize Anthropic provider.
        
        Args:
            config: Configuration instance with ANTHROPIC_API_KEY
        
        Raises:
            AuthenticationError: If API key is not configured
        """
        super().__init__(config)
        
        if not config.ANTHROPIC_API_KEY:
            raise AuthenticationError(
                "ANTHROPIC_API_KEY not configured. "
                "Set it in .env or via 'aise config set ANTHROPIC_API_KEY <key>'"
            )
        
        self._client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
        self._default_model = getattr(config, "ANTHROPIC_MODEL", "claude-3-sonnet-20240229")
        
        logger.info(
            "anthropic_provider_initialized",
            default_model=self._default_model
        )
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((anthropic.RateLimitError, anthropic.APIConnectionError)),
        reraise=True
    )
    async def complete(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None
    ) -> CompletionResult:
        """Generate a completion using Claude.
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            system_prompt: Optional system prompt
            temperature: Sampling temperature (0.0 to 1.0)
            max_tokens: Maximum tokens to generate (default: 4096)
            model: Specific Claude model (default: claude-3-sonnet)
        
        Returns:
            CompletionResult with generated text and metadata
        
        Raises:
            ProviderError: If API call fails
            AuthenticationError: If API key is invalid
        """
        model = model or self._default_model
        max_tokens = max_tokens or 4096
        
        try:
            logger.info(
                "anthropic_completion_request",
                model=model,
                message_count=len(messages),
                temperature=temperature,
                max_tokens=max_tokens
            )
            
            # Build request parameters
            request_params = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens
            }
            
            if system_prompt:
                request_params["system"] = system_prompt
            
            # Make API call
            response = await self._client.messages.create(**request_params)
            
            # Extract content
            content = response.content[0].text if response.content else ""
            
            # Build usage stats
            usage = TokenUsage(
                prompt_tokens=response.usage.input_tokens,
                completion_tokens=response.usage.output_tokens,
                total_tokens=response.usage.input_tokens + response.usage.output_tokens,
                estimated_cost_usd=self.estimate_cost(
                    response.usage.input_tokens,
                    response.usage.output_tokens,
                    model
                )
            )
            
            logger.info(
                "anthropic_completion_success",
                model=model,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                cost_usd=usage.estimated_cost_usd
            )
            
            return CompletionResult(
                content=content,
                model=model,
                usage=usage,
                provider="anthropic",
                finish_reason=response.stop_reason
            )
            
        except anthropic.AuthenticationError as e:
            logger.error("anthropic_auth_error", error=str(e))
            raise AuthenticationError(f"Anthropic authentication failed: {str(e)}")
        
        except anthropic.RateLimitError as e:
            logger.error("anthropic_rate_limit", error=str(e))
            raise ProviderError(f"Anthropic rate limit exceeded: {str(e)}")
        
        except Exception as e:
            logger.error("anthropic_completion_failed", error=str(e), model=model)
            raise ProviderError(f"Anthropic completion failed: {str(e)}")
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((anthropic.RateLimitError, anthropic.APIConnectionError)),
        reraise=True
    )
    async def stream_complete(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None
    ) -> AsyncIterator[str]:
        """Stream completion tokens from Claude.
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            system_prompt: Optional system prompt
            temperature: Sampling temperature (0.0 to 1.0)
            max_tokens: Maximum tokens to generate (default: 4096)
            model: Specific Claude model (default: claude-3-sonnet)
        
        Yields:
            String tokens as they are generated
        
        Raises:
            ProviderError: If API call fails
            AuthenticationError: If API key is invalid
        """
        model = model or self._default_model
        max_tokens = max_tokens or 4096
        
        try:
            logger.info(
                "anthropic_stream_request",
                model=model,
                message_count=len(messages),
                temperature=temperature
            )
            
            # Build request parameters
            request_params = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": True
            }
            
            if system_prompt:
                request_params["system"] = system_prompt
            
            # Stream response
            async with self._client.messages.stream(**request_params) as stream:
                async for text in stream.text_stream:
                    yield text
            
            logger.info("anthropic_stream_complete", model=model)
            
        except anthropic.AuthenticationError as e:
            logger.error("anthropic_auth_error", error=str(e))
            raise AuthenticationError(f"Anthropic authentication failed: {str(e)}")
        
        except anthropic.RateLimitError as e:
            logger.error("anthropic_rate_limit", error=str(e))
            raise ProviderError(f"Anthropic rate limit exceeded: {str(e)}")
        
        except Exception as e:
            logger.error("anthropic_stream_failed", error=str(e), model=model)
            raise ProviderError(f"Anthropic streaming failed: {str(e)}")
    
    def count_tokens(self, text: str, model: Optional[str] = None) -> int:
        """Count tokens in text using Anthropic's tokenizer.
        
        Args:
            text: Text to count tokens for
            model: Model to use (ignored, uses Claude tokenizer)
        
        Returns:
            Approximate token count
        """
        # Anthropic uses a similar tokenizer to GPT
        # Rough approximation: 1 token ≈ 4 characters
        return len(text) // 4
    
    def estimate_cost(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        model: Optional[str] = None
    ) -> float:
        """Estimate cost in USD for token usage.
        
        Args:
            prompt_tokens: Number of prompt tokens
            completion_tokens: Number of completion tokens
            model: Model used (default: claude-3-sonnet)
        
        Returns:
            Estimated cost in USD
        """
        model = model or self._default_model
        
        # Get pricing for model; fall back to default if not in table
        pricing = ANTHROPIC_PRICING.get(model, _DEFAULT_PRICING)
        if model not in ANTHROPIC_PRICING:
            logger.debug("anthropic_pricing_unknown_model", model=model, using_default=True)
        
        # Calculate cost (pricing is per 1M tokens)
        input_cost = (prompt_tokens / 1_000_000) * pricing["input"]
        output_cost = (completion_tokens / 1_000_000) * pricing["output"]
        
        return input_cost + output_cost
