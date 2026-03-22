# aise/core/logging.py
"""
Structured logging configuration with PII redaction and API key masking.

This module provides comprehensive logging capabilities including:
- JSON output for production (container log aggregation)
- Pretty console output for development
- PII redaction (emails, phone numbers, IP addresses, credit cards)
- API key masking (show first and last 4 characters only)
- Context variables for request tracing
- Multiple log levels support
- Log filtering and formatting
"""

import logging
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, List, Tuple
import structlog
from structlog.types import EventDict, Processor


# ============================================================================
# PII Redaction Patterns
# ============================================================================

# Email pattern: matches standard email addresses
EMAIL_PATTERN = re.compile(
    r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
)

# Phone number pattern: requires explicit country code or parenthesised area code
# to avoid false positives on version numbers / port numbers
PHONE_PATTERN = re.compile(
    r'(?:'
    r'\+\d{1,3}[-.\s]?\(?\d{1,4}\)?[-.\s]?\d{1,4}[-.\s]?\d{1,9}'  # intl: +1-234-567-8900
    r'|'
    r'\(\d{3}\)[-.\s]?\d{3}[-.\s]?\d{4}'  # US with parens: (234) 567-8900
    r')'
)

# IP address pattern: matches IPv4 addresses
IPV4_PATTERN = re.compile(
    r'\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}'
    r'(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b'
)

# IPv6 pattern: matches IPv6 addresses
IPV6_PATTERN = re.compile(
    r'\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b|'
    r'\b(?:[0-9a-fA-F]{1,4}:){1,7}:\b|'
    r'\b(?:[0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}\b'
)

# Credit card pattern: matches common credit card formats
CREDIT_CARD_PATTERN = re.compile(
    r'\b(?:\d{4}[-\s]?){3}\d{4}\b'
)

# API key patterns: matches common API key formats
# Matches keys like: sk-abc123..., api_key_abc123..., etc.
API_KEY_PATTERN = re.compile(
    r'\b(?:sk|pk|api[_-]?key)[_-]?[a-zA-Z0-9]{16,}\b',
    re.IGNORECASE
)

# AWS access key pattern
AWS_KEY_PATTERN = re.compile(
    r'\b(?:AKIA|ASIA)[0-9A-Z]{16}\b'
)


# ============================================================================
# PII Configuration
# ============================================================================

@dataclass
class PIIConfig:
    """Controls which PII redaction rules are active.

    All built-in rules are enabled by default. Set any flag to False to
    disable it, or add custom (pattern, replacement) pairs via
    ``extra_patterns``.

    Example — disable IP redaction and add a custom SSN rule::

        import re
        from aise.core.logging import PIIConfig, setup_logging

        config = PIIConfig(
            redact_ip=False,
            extra_patterns=[
                (re.compile(r'\\b\\d{3}-\\d{2}-\\d{4}\\b'), '[SSN_REDACTED]')
            ]
        )
        setup_logging(pii_config=config)
    """
    redact_email: bool = True
    redact_phone: bool = True
    redact_ip: bool = True
    redact_credit_card: bool = True
    redact_api_keys: bool = True
    # List of (compiled_pattern, replacement_string) for custom rules
    extra_patterns: List[Tuple[re.Pattern, str]] = field(default_factory=list)


# ============================================================================
# PII Redaction Functions
# ============================================================================

def redact_email(text: str) -> str:
    """
    Redact email addresses from text.
    
    Args:
        text: Input text potentially containing emails
        
    Returns:
        Text with emails replaced by [EMAIL_REDACTED]
    """
    return EMAIL_PATTERN.sub('[EMAIL_REDACTED]', text)


def redact_phone(text: str) -> str:
    """
    Redact phone numbers from text.
    
    Args:
        text: Input text potentially containing phone numbers
        
    Returns:
        Text with phone numbers replaced by [PHONE_REDACTED]
    """
    return PHONE_PATTERN.sub('[PHONE_REDACTED]', text)


def redact_ip(text: str) -> str:
    """
    Redact IP addresses (IPv4 and IPv6) from text.
    
    Args:
        text: Input text potentially containing IP addresses
        
    Returns:
        Text with IPs replaced by [IP_REDACTED]
    """
    text = IPV4_PATTERN.sub('[IP_REDACTED]', text)
    text = IPV6_PATTERN.sub('[IP_REDACTED]', text)
    return text


def redact_credit_card(text: str) -> str:
    """
    Redact credit card numbers from text.
    
    Args:
        text: Input text potentially containing credit card numbers
        
    Returns:
        Text with credit cards replaced by [CC_REDACTED]
    """
    return CREDIT_CARD_PATTERN.sub('[CC_REDACTED]', text)


def mask_api_key(key: str) -> str:
    """
    Mask API key showing only first and last 4 characters.
    
    Args:
        key: API key to mask
        
    Returns:
        Masked key in format: "abcd****wxyz" or "****" if too short
    """
    if not key or len(key) <= 8:
        return "****"
    return f"{key[:4]}****{key[-4:]}"


def redact_api_keys(text: str) -> str:
    """
    Redact API keys from text, showing only first and last 4 characters.
    
    Args:
        text: Input text potentially containing API keys
        
    Returns:
        Text with API keys masked
    """
    def mask_match(match: re.Match) -> str:
        return mask_api_key(match.group(0))
    
    text = API_KEY_PATTERN.sub(mask_match, text)
    text = AWS_KEY_PATTERN.sub(mask_match, text)
    return text


def redact_pii(text: str, config: Optional["PIIConfig"] = None) -> str:
    """
    Apply PII redaction rules to text, controlled by config.

    Args:
        text: Input text potentially containing PII
        config: PIIConfig instance (uses all rules enabled if None)

    Returns:
        Text with PII redacted according to config
    """
    if config is None:
        config = PIIConfig()
    if config.redact_email:
        text = redact_email(text)
    if config.redact_phone:
        text = redact_phone(text)
    if config.redact_ip:
        text = redact_ip(text)
    if config.redact_credit_card:
        text = redact_credit_card(text)
    if config.redact_api_keys:
        text = redact_api_keys(text)
    for pattern, replacement in config.extra_patterns:
        text = pattern.sub(replacement, text)
    return text


# ============================================================================
# Structlog Processors
# ============================================================================

def pii_redaction_processor(
    logger: logging.Logger,
    method_name: str,
    event_dict: EventDict
) -> EventDict:
    """
    Structlog processor that redacts PII from all string values in event dict.

    Uses the module-level ``_pii_config``. Call ``setup_logging(pii_config=...)``
    to customise which rules are active.
    """
    def redact_value(value: Any) -> Any:
        """Recursively redact PII from values."""
        if isinstance(value, str):
            return redact_pii(value, _pii_config)
        elif isinstance(value, dict):
            return {k: redact_value(v) for k, v in value.items()}
        elif isinstance(value, (list, tuple)):
            return type(value)(redact_value(item) for item in value)
        return value

    for key, value in event_dict.items():
        event_dict[key] = redact_value(value)

    return event_dict


# Module-level config — replaced by setup_logging(pii_config=...) at startup
_pii_config: PIIConfig = PIIConfig()


def add_context_processor(
    logger: logging.Logger,
    method_name: str,
    event_dict: EventDict
) -> EventDict:
    """
    Add contextual information to log events.
    
    This processor adds useful context like logger name and method.
    
    Args:
        logger: Logger instance
        method_name: Name of the logging method
        event_dict: Event dictionary to process
        
    Returns:
        Event dictionary with context added
    """
    event_dict['logger'] = getattr(logger, 'name', None) or getattr(logger, '_name', None) or ''
    event_dict['level'] = method_name
    return event_dict


# ============================================================================
# Logging Configuration
# ============================================================================

def setup_logging(
    log_level: str = "INFO",
    debug: bool = False,
    json_output: bool = False,
    enable_pii_redaction: bool = True,
    pii_config: Optional[PIIConfig] = None
) -> None:
    """
    Configure structured logging with structlog.

    Args:
        log_level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        debug: Enable debug mode with verbose pretty console logging
        json_output: Force JSON output (overrides debug mode)
        enable_pii_redaction: Enable PII redaction in logs
        pii_config: Fine-grained PIIConfig (overrides enable_pii_redaction
            when provided). Use this to toggle individual rules or add
            custom patterns without touching source code.

    Example::

        # Disable phone + IP redaction, add custom SSN rule
        import re
        from aise.core.logging import PIIConfig, setup_logging

        setup_logging(
            pii_config=PIIConfig(
                redact_phone=False,
                redact_ip=False,
                extra_patterns=[(re.compile(r'\\b\\d{3}-\\d{2}-\\d{4}\\b'), '[SSN_REDACTED]')]
            )
        )
    """
    global _pii_config

    # Override log level if debug is enabled
    if debug:
        log_level = "DEBUG"

    # Update module-level PII config
    if pii_config is not None:
        _pii_config = pii_config
    elif not enable_pii_redaction:
        # Convenience: disable all rules when enable_pii_redaction=False
        _pii_config = PIIConfig(
            redact_email=False,
            redact_phone=False,
            redact_ip=False,
            redact_credit_card=False,
            redact_api_keys=False,
        )
    else:
        _pii_config = PIIConfig()  # all rules on

    # Determine output format — use pretty console unless JSON explicitly requested
    use_json = json_output
    
    # Configure standard logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper())
    )

    # Silence noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("chromadb").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    
    # Build processor chain
    processors: List[Processor] = [
        # Add context variables from contextvars
        structlog.contextvars.merge_contextvars,
        
        # Add log level to event dict
        structlog.processors.add_log_level,
        
        # Add logger name and context
        add_context_processor,
        
        # Add timestamp in ISO format
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        
        # Add stack info for exceptions
        structlog.processors.StackInfoRenderer(),
        
        # Format exception info
        structlog.processors.format_exc_info,
    ]

    # Add PII redaction processor — active rules are controlled by _pii_config
    if enable_pii_redaction or pii_config is not None:
        processors.append(pii_redaction_processor)
    
    # Add final renderer based on output format
    if use_json:
        # JSON output for production/container environments
        processors.append(structlog.processors.JSONRenderer())
    else:
        # Pretty console output for development
        processors.append(
            structlog.dev.ConsoleRenderer(
                colors=True,
                exception_formatter=structlog.dev.plain_traceback
            )
        )
    
    # Configure structlog
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, log_level.upper())
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.BoundLogger:
    """
    Get a structured logger instance.
    
    Args:
        name: Logger name (typically __name__ of the module)
        
    Returns:
        Configured structlog BoundLogger instance
        
    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("Processing ticket", ticket_id="12345")
        >>> logger.error("Failed to connect", service="postgres", error=str(e))
    """
    return structlog.get_logger(name)


# ============================================================================
# Context Management
# ============================================================================

def bind_context(**kwargs: Any) -> None:
    """
    Bind context variables that will be included in all subsequent log messages.
    
    This is useful for request tracing, adding request IDs, user IDs, etc.
    
    Args:
        **kwargs: Key-value pairs to bind to logging context
        
    Example:
        >>> bind_context(request_id="abc-123", user_id="user-456")
        >>> logger.info("Processing request")  # Will include request_id and user_id
    """
    structlog.contextvars.bind_contextvars(**kwargs)


def unbind_context(*keys: str) -> None:
    """
    Unbind specific context variables.
    
    Args:
        *keys: Keys to unbind from logging context
        
    Example:
        >>> unbind_context("request_id", "user_id")
    """
    structlog.contextvars.unbind_contextvars(*keys)


def clear_context() -> None:
    """
    Clear all context variables.
    
    Example:
        >>> clear_context()
    """
    structlog.contextvars.clear_contextvars()


# ============================================================================
# Utility Functions
# ============================================================================

def mask_sensitive_dict(
    data: Dict[str, Any],
    sensitive_keys: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Mask sensitive values in a dictionary.
    
    Args:
        data: Dictionary potentially containing sensitive data
        sensitive_keys: List of keys to mask (default: common sensitive keys)
        
    Returns:
        Dictionary with sensitive values masked
        
    Example:
        >>> data = {"api_key": "sk-abc123xyz789", "username": "john"}
        >>> masked = mask_sensitive_dict(data, ["api_key"])
        >>> print(masked)
        {'api_key': 'sk-a****x789', 'username': 'john'}
    """
    if sensitive_keys is None:
        # Matches the same keywords used in config.py to_dict() auto-detection
        sensitive_keys = ["KEY", "SECRET", "PASSWORD", "TOKEN", "CREDENTIAL"]
    
    result = {}
    for key, value in data.items():
        # Check if key contains any sensitive keyword (case-insensitive)
        is_sensitive = any(
            sensitive_word in key.upper()
            for sensitive_word in sensitive_keys
        )
        
        if is_sensitive and isinstance(value, str):
            result[key] = mask_api_key(value)
        elif isinstance(value, dict):
            result[key] = mask_sensitive_dict(value, sensitive_keys)
        else:
            result[key] = value
    
    return result


# ============================================================================
# Initialization
# ============================================================================

# Initialize with default settings
# This will be reconfigured when the application starts with proper config
setup_logging()
