# aise/ai_engine/local_provider.py
"""Ollama local LLM provider implementation.

This module implements the LLMProvider interface for Ollama, enabling
local LLM inference without external API calls.

Example usage:
    >>> from aise.ai_engine.local_provider import OllamaProvider
    >>> from aise.core.config import get_config
    >>> 
    >>> config = get_config()
    >>> provider = OllamaProvider(config)
    >>> 
    >>> messages = [{"role": "user", "content": "Explain Terraform"}]
    >>> result = await provider.complete(messages)
    >>> print(result.content)
"""

from typing import List, Dict, Optional, AsyncIterator
import httpx
import json
import structlog

from aise.ai_engine.base import LLMProvider, CompletionResult, TokenUsage
from aise.core.exceptions import ProviderError

logger = structlog.get_logger(__name__)


class OllamaProvider(LLMProvider):
    """Ollama local LLM provider implementation.
    
    Supports any model available in Ollama (llama2, mistral, codellama, etc.)
    with streaming and local inference.
    """
    
    def __init__(self, config):
        """Initialize Ollama provider.
        
        Args:
            config: Configuration instance with OLLAMA_BASE_URL
        """
        super().__init__(config)
        
        self._base_url = getattr(config, "OLLAMA_BASE_URL", "http://localhost:11434")
        self._default_model = getattr(config, "OLLAMA_MODEL", "phi3")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=120.0  # Longer timeout for local inference
        )
        
        logger.info(
            "ollama_provider_initialized",
            default_model=self._default_model,
            base_url=self._base_url
        )
    
    async def complete(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None
    ) -> CompletionResult:
        """Generate a completion using Ollama.
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            system_prompt: Optional system prompt
            temperature: Sampling temperature (0.0 to 2.0)
            max_tokens: Maximum tokens to generate (default: 4096)
            model: Specific Ollama model (default: llama2)
        
        Returns:
            CompletionResult with generated text and metadata
        
        Raises:
            ProviderError: If API call fails
        """
        model = model or self._default_model
        max_tokens = max_tokens or 4096
        
        try:
            logger.info(
                "ollama_completion_request",
                model=model,
                message_count=len(messages),
                temperature=temperature,
                max_tokens=max_tokens
            )
            
            # Prepend system prompt if provided
            full_messages = []
            if system_prompt:
                full_messages.append({"role": "system", "content": system_prompt})
            full_messages.extend(messages)
            
            # Build request payload
            payload = {
                "model": model,
                "messages": full_messages,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens
                }
            }
            
            # Make API call
            response = await self._client.post("/api/chat", json=payload)
            response.raise_for_status()
            
            data = response.json()
            
            # Extract content
            content = data["message"]["content"]
            
            # Build usage stats (Ollama provides these in the response)
            prompt_tokens = data.get("prompt_eval_count", 0)
            completion_tokens = data.get("eval_count", 0)
            
            usage = TokenUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                estimated_cost_usd=0.0  # Local inference is free
            )
            
            logger.info(
                "ollama_completion_success",
                model=model,
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens
            )
            
            return CompletionResult(
                content=content,
                model=model,
                usage=usage,
                provider="ollama",
                finish_reason=data.get("done_reason")
            )
            
        except httpx.HTTPStatusError as e:
            body = e.response.text[:200] if e.response.text else "(no body)"
            logger.error("ollama_http_error", status=e.response.status_code, body=body)
            raise ProviderError(f"Ollama API error {e.response.status_code}: {body}")
        
        except httpx.ConnectError as e:
            logger.error("ollama_connection_error", error=str(e))
            raise ProviderError(
                f"Cannot connect to Ollama at {self._base_url}. "
                "Ensure Ollama is running with 'ollama serve'"
            )
        
        except Exception as e:
            logger.error("ollama_completion_failed", error=str(e), exc_type=type(e).__name__, model=model)
            raise ProviderError(f"Ollama completion failed: {type(e).__name__}: {str(e)}")
    
    async def stream_complete(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None
    ) -> AsyncIterator[str]:
        """Stream completion tokens from Ollama.
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            system_prompt: Optional system prompt
            temperature: Sampling temperature (0.0 to 2.0)
            max_tokens: Maximum tokens to generate (default: 4096)
            model: Specific Ollama model (default: llama2)
        
        Yields:
            String tokens as they are generated
        
        Raises:
            ProviderError: If API call fails
        """
        model = model or self._default_model
        max_tokens = max_tokens or 4096
        
        try:
            logger.info(
                "ollama_stream_request",
                model=model,
                message_count=len(messages),
                temperature=temperature
            )
            
            # Prepend system prompt if provided
            full_messages = []
            if system_prompt:
                full_messages.append({"role": "system", "content": system_prompt})
            full_messages.extend(messages)
            
            # Build request payload
            payload = {
                "model": model,
                "messages": full_messages,
                "stream": True,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens
                }
            }
            
            # Stream response
            async with self._client.stream("POST", "/api/chat", json=payload) as response:
                response.raise_for_status()
                
                async for line in response.aiter_lines():
                    if line:
                        try:
                            data = json.loads(line)
                            
                            if "message" in data and "content" in data["message"]:
                                yield data["message"]["content"]
                            
                            if data.get("done", False):
                                break
                        except json.JSONDecodeError:
                            continue
            
            logger.info("ollama_stream_complete", model=model)
            
        except httpx.HTTPStatusError as e:
            body = e.response.text[:200] if e.response.text else "(no body)"
            logger.error("ollama_http_error", status=e.response.status_code, body=body)
            raise ProviderError(f"Ollama API error {e.response.status_code}: {body}")
        
        except httpx.ConnectError as e:
            logger.error("ollama_connection_error", error=str(e))
            raise ProviderError(
                f"Cannot connect to Ollama at {self._base_url}. "
                "Ensure Ollama is running with 'ollama serve'"
            )
        
        except Exception as e:
            logger.error("ollama_stream_failed", error=str(e), exc_type=type(e).__name__, model=model)
            raise ProviderError(f"Ollama streaming failed: {type(e).__name__}: {str(e)}")
    
    def count_tokens(self, text: str, model: Optional[str] = None) -> int:
        """Count tokens in text (approximate).
        
        Args:
            text: Text to count tokens for
            model: Model to use (ignored)
        
        Returns:
            Approximate token count
        """
        # Approximate: 1 token ≈ 4 characters
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
            model: Model used (ignored)
        
        Returns:
            0.0 (local inference is free)
        """
        return 0.0  # Local inference has no API costs
    
    async def __aenter__(self):
        """Async context manager entry."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - close httpx client."""
        await self._client.aclose()
