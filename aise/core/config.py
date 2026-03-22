# aise/core/config.py
"""Pydantic settings for configuration management with system-level credential detection."""

import os
from pathlib import Path
from typing import Optional, Literal, Dict, Any
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
import structlog

logger = structlog.get_logger(__name__)


class Config(BaseSettings):
    """
    AiSE configuration with multi-source loading and validation.
    
    Configuration precedence (highest to lowest):
    1. Environment variables
    2. .env file in project directory
    3. Config UI database settings (future)
    4. System-level config files (~/.aws/config, ~/.kube/config, etc.)
    5. Default values
    
    System-level credential detection:
    - AWS: ~/.aws/credentials, ~/.aws/config, AWS_PROFILE, IAM role
    - Kubernetes: KUBECONFIG, ~/.kube/config
    - SSH: ~/.ssh/config
    - Docker: ~/.docker/config.json
    """
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )
    
    # -------------------------------------------------------------------------
    # LLM Provider Configuration
    # -------------------------------------------------------------------------
    LLM_PROVIDER: Literal["anthropic", "openai", "deepseek", "ollama"] = Field(
        default="anthropic",
        description="Primary LLM provider"
    )
    
    ANTHROPIC_API_KEY: Optional[str] = Field(
        default=None,
        description="Anthropic Claude API key"
    )
    
    OPENAI_API_KEY: Optional[str] = Field(
        default=None,
        description="OpenAI API key"
    )
    
    DEEPSEEK_API_KEY: Optional[str] = Field(
        default=None,
        description="DeepSeek API key"
    )
    
    OLLAMA_BASE_URL: str = Field(
        default="http://localhost:11434",
        description="Ollama base URL for local LLM inference"
    )
    
    OLLAMA_MODEL: str = Field(
        default="llama3",
        description="Ollama model name to use for inference"
    )
    
    # -------------------------------------------------------------------------
    # Operational Mode
    # -------------------------------------------------------------------------
    AISE_MODE: Literal["interactive", "approval", "autonomous"] = Field(
        default="approval",
        description="Operational mode: interactive, approval, or autonomous"
    )
    
    # -------------------------------------------------------------------------
    # Database Configuration
    # -------------------------------------------------------------------------
    POSTGRES_URL: str = Field(
        ...,
        description="PostgreSQL connection string (required)"
    )
    
    # DATABASE_URL is an alias for POSTGRES_URL (for compatibility)
    DATABASE_URL: Optional[str] = Field(
        default=None,
        description="PostgreSQL connection string (alias for POSTGRES_URL)"
    )
    
    REDIS_URL: str = Field(
        ...,
        description="Redis connection string (required)"
    )
    
    CHROMA_HOST: str = Field(
        default="localhost",
        description="ChromaDB host"
    )
    
    CHROMA_PORT: int = Field(
        default=8000,
        description="ChromaDB port"
    )
    
    # -------------------------------------------------------------------------
    # Ticket System Configuration
    # -------------------------------------------------------------------------
    ZENDESK_SUBDOMAIN: Optional[str] = Field(
        default=None,
        description="Zendesk subdomain"
    )
    
    ZENDESK_EMAIL: Optional[str] = Field(
        default=None,
        description="Zendesk admin email"
    )
    
    ZENDESK_API_TOKEN: Optional[str] = Field(
        default=None,
        description="Zendesk API token"
    )
    
    ZENDESK_URL: Optional[str] = Field(
        default=None,
        description="Full Zendesk URL (overrides subdomain)"
    )
    
    FRESHDESK_DOMAIN: Optional[str] = Field(
        default=None,
        description="Freshdesk domain"
    )
    
    FRESHDESK_API_KEY: Optional[str] = Field(
        default=None,
        description="Freshdesk API key"
    )
    
    FRESHDESK_URL: Optional[str] = Field(
        default=None,
        description="Full Freshdesk URL (overrides domain)"
    )
    
    EMAIL_IMAP_HOST: Optional[str] = Field(
        default=None,
        description="IMAP server host"
    )
    
    EMAIL_IMAP_PORT: int = Field(
        default=993,
        description="IMAP server port"
    )
    
    EMAIL_IMAP_USERNAME: Optional[str] = Field(
        default=None,
        description="IMAP username"
    )
    
    EMAIL_IMAP_PASSWORD: Optional[str] = Field(
        default=None,
        description="IMAP password"
    )
    
    EMAIL_SMTP_HOST: Optional[str] = Field(
        default=None,
        description="SMTP server host"
    )
    
    EMAIL_SMTP_PORT: int = Field(
        default=587,
        description="SMTP server port"
    )
    
    EMAIL_SMTP_USERNAME: Optional[str] = Field(
        default=None,
        description="SMTP username"
    )
    
    EMAIL_SMTP_PASSWORD: Optional[str] = Field(
        default=None,
        description="SMTP password"
    )
    
    SLACK_BOT_TOKEN: Optional[str] = Field(
        default=None,
        description="Slack bot token"
    )
    
    SLACK_SIGNING_SECRET: Optional[str] = Field(
        default=None,
        description="Slack signing secret for webhook verification"
    )
    
    # -------------------------------------------------------------------------
    # Browser Automation Configuration
    # -------------------------------------------------------------------------
    USE_BROWSER_FALLBACK: bool = Field(
        default=False,
        description="Enable browser fallback when APIs are unavailable"
    )
    
    BROWSER_HEADLESS: bool = Field(
        default=True,
        description="Run browser in headless mode"
    )
    
    CUSTOM_SUPPORT_URL: Optional[str] = Field(
        default=None,
        description="Custom support platform URL for browser automation"
    )
    
    # -------------------------------------------------------------------------
    # Cloud Provider Credentials (Auto-detected from system)
    # -------------------------------------------------------------------------
    AWS_PROFILE: Optional[str] = Field(
        default=None,
        description="AWS profile name (auto-detected from ~/.aws/config)"
    )
    
    AWS_DEFAULT_REGION: Optional[str] = Field(
        default=None,
        description="AWS default region"
    )
    
    AWS_ACCESS_KEY_ID: Optional[str] = Field(
        default=None,
        description="AWS access key ID (auto-detected)"
    )
    
    AWS_SECRET_ACCESS_KEY: Optional[str] = Field(
        default=None,
        description="AWS secret access key (auto-detected)"
    )
    
    KUBECONFIG: Optional[str] = Field(
        default=None,
        description="Kubernetes config file path (auto-detected)"
    )
    
    GOOGLE_APPLICATION_CREDENTIALS: Optional[str] = Field(
        default=None,
        description="Google Cloud service account JSON path"
    )
    
    AZURE_CONFIG_DIR: Optional[str] = Field(
        default=None,
        description="Azure CLI config directory"
    )
    
    # -------------------------------------------------------------------------
    # Observability Configuration
    # -------------------------------------------------------------------------
    LANGSMITH_API_KEY: Optional[str] = Field(
        default=None,
        description="LangSmith API key for LLM observability"
    )
    
    OTEL_EXPORTER_OTLP_ENDPOINT: Optional[str] = Field(
        default=None,
        description="OpenTelemetry OTLP endpoint"
    )
    
    PROMETHEUS_PORT: int = Field(
        default=9090,
        description="Prometheus metrics port"
    )
    
    # -------------------------------------------------------------------------
    # Security Configuration
    # -------------------------------------------------------------------------
    CREDENTIAL_VAULT_KEY: Optional[str] = Field(
        default=None,
        description="Encryption key for credential vault"
    )
    
    WEBHOOK_SECRET: Optional[str] = Field(
        default=None,
        description="Webhook signature secret"
    )
    
    WEBHOOK_ALLOWED_IPS: Optional[str] = Field(
        default=None,
        description="Comma-separated list of allowed webhook source IPs"
    )
    
    # -------------------------------------------------------------------------
    # Tool Execution Configuration
    # -------------------------------------------------------------------------
    TOOL_EXECUTION_TIMEOUT: int = Field(
        default=30,
        description="Command execution timeout in seconds"
    )
    
    MAX_CONCURRENT_TOOLS: int = Field(
        default=5,
        description="Maximum concurrent tool executions"
    )
    
    # -------------------------------------------------------------------------
    # Knowledge Engine Configuration
    # -------------------------------------------------------------------------
    CHROMA_PERSIST_PATH: str = Field(
        default="./data/chroma",
        description="ChromaDB persistent storage path"
    )
    
    KNOWLEDGE_CRAWL_MAX_DEPTH: int = Field(
        default=3,
        description="Maximum crawl depth for documentation"
    )
    
    KNOWLEDGE_CHUNK_SIZE: int = Field(
        default=1000,
        description="Chunk size for text splitting"
    )
    
    KNOWLEDGE_CHUNK_OVERLAP: int = Field(
        default=150,
        description="Chunk overlap for context preservation"
    )
    
    KNOWLEDGE_MIN_REINIT_HOURS: int = Field(
        default=24,
        description="Minimum hours before re-indexing a source (unless --force)"
    )
    
    EMBEDDING_MODEL: Literal["openai", "sentence-transformers"] = Field(
        default="openai",
        description="Embedding model provider"
    )
    
    LOCAL_EMBEDDING_MODEL: str = Field(
        default="all-MiniLM-L6-v2",
        description="Local embedding model name for sentence-transformers"
    )
    
    MAX_CRAWL_PAGES: int = Field(
        default=1000,
        description="Maximum pages to crawl per documentation source"
    )
    
    MAX_CRAWL_DEPTH: int = Field(
        default=3,
        description="Crawl depth limit (deprecated, use KNOWLEDGE_CRAWL_MAX_DEPTH)"
    )
    
    CHUNK_SIZE: int = Field(
        default=1000,
        description="Chunk size for text splitting (deprecated, use KNOWLEDGE_CHUNK_SIZE)"
    )
    
    CHUNK_OVERLAP: int = Field(
        default=150,
        description="Chunk overlap for context preservation (deprecated, use KNOWLEDGE_CHUNK_OVERLAP)"
    )
    
    # -------------------------------------------------------------------------
    # Web UI Configuration
    # -------------------------------------------------------------------------
    CONFIG_UI_PORT: int = Field(
        default=8080,
        description="Config UI port"
    )
    
    WEBHOOK_SERVER_PORT: int = Field(
        default=8000,
        description="Webhook server port"
    )
    
    # -------------------------------------------------------------------------
    # Development Configuration
    # -------------------------------------------------------------------------
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        description="Log level"
    )
    
    DEBUG: bool = Field(
        default=False,
        description="Enable debug mode with verbose logging"
    )
    
    # -------------------------------------------------------------------------
    # Validators
    # -------------------------------------------------------------------------
    
    @field_validator("POSTGRES_URL")
    @classmethod
    def validate_postgres_url(cls, v: str) -> str:
        """Validate PostgreSQL connection string format."""
        if not v:
            raise ValueError("POSTGRES_URL is required")
        if not v.startswith(("postgresql://", "postgres://")):
            raise ValueError("POSTGRES_URL must start with postgresql:// or postgres://")
        return v
    
    @field_validator("REDIS_URL")
    @classmethod
    def validate_redis_url(cls, v: str) -> str:
        """Validate Redis connection string format."""
        if not v:
            raise ValueError("REDIS_URL is required")
        if not v.startswith("redis://"):
            raise ValueError("REDIS_URL must start with redis://")
        return v
    
    @model_validator(mode="after")
    def validate_llm_provider(self) -> "Config":
        """Validate that at least one LLM provider API key is configured."""
        # Handle DATABASE_URL alias for POSTGRES_URL
        if self.DATABASE_URL and not self.POSTGRES_URL:
            self.POSTGRES_URL = self.DATABASE_URL
        elif not self.DATABASE_URL and self.POSTGRES_URL:
            self.DATABASE_URL = self.POSTGRES_URL
        
        provider_keys = {
            "anthropic": self.ANTHROPIC_API_KEY,
            "openai": self.OPENAI_API_KEY,
            "deepseek": self.DEEPSEEK_API_KEY,
            "ollama": self.OLLAMA_BASE_URL
        }
        
        # Check if the selected provider has credentials
        selected_provider = self.LLM_PROVIDER
        if selected_provider == "ollama":
            # Ollama doesn't need API key, just URL
            if not self.OLLAMA_BASE_URL:
                raise ValueError("OLLAMA_BASE_URL is required when using ollama provider")
        else:
            if not provider_keys.get(selected_provider):
                raise ValueError(
                    f"API key for selected LLM provider '{selected_provider}' is not configured. "
                    f"Please set {selected_provider.upper()}_API_KEY"
                )
        
        # Warn if no fallback providers are configured
        configured_providers = [
            name for name, key in provider_keys.items()
            if key and (name == "ollama" or key)
        ]
        
        # Only warn about single provider if not using ollama (ollama-only is a valid local setup)
        if len(configured_providers) == 1 and selected_provider != "ollama":
            logger.warning(
                "Only one LLM provider configured. Consider adding fallback providers for reliability.",
                provider=selected_provider
            )
        
        return self
    
    @model_validator(mode="after")
    def validate_embedding_model(self) -> "Config":
        """Validate embedding model configuration."""
        if self.EMBEDDING_MODEL == "openai" and not self.OPENAI_API_KEY:
            raise ValueError(
                "OPENAI_API_KEY is required when EMBEDDING_MODEL is set to 'openai'"
            )
        return self
    
    # -------------------------------------------------------------------------
    # System-level credential detection
    # -------------------------------------------------------------------------
    
    def detect_system_credentials(self) -> Dict[str, Dict[str, Any]]:
        """
        Detect credentials from system-level configuration files.
        
        Returns:
            Dictionary mapping credential type to detected values and sources.
        """
        detected = {}
        
        # AWS credentials detection
        aws_creds = self._detect_aws_credentials()
        if aws_creds:
            detected["aws"] = aws_creds
        
        # Kubernetes credentials detection
        kube_creds = self._detect_kubernetes_credentials()
        if kube_creds:
            detected["kubernetes"] = kube_creds
        
        # SSH config detection
        ssh_config = self._detect_ssh_config()
        if ssh_config:
            detected["ssh"] = ssh_config
        
        # Docker config detection
        docker_config = self._detect_docker_config()
        if docker_config:
            detected["docker"] = docker_config
        
        return detected
    
    def _detect_aws_credentials(self) -> Optional[Dict[str, Any]]:
        """Detect AWS credentials from standard locations."""
        sources = []
        
        # Check environment variables
        if os.environ.get("AWS_ACCESS_KEY_ID") and os.environ.get("AWS_SECRET_ACCESS_KEY"):
            sources.append("environment variables")
        
        # Check AWS profile
        if self.AWS_PROFILE or os.environ.get("AWS_PROFILE"):
            profile = self.AWS_PROFILE or os.environ.get("AWS_PROFILE")
            sources.append(f"AWS profile: {profile}")
        
        # Check ~/.aws/credentials
        aws_creds_path = Path.home() / ".aws" / "credentials"
        if aws_creds_path.exists():
            sources.append(str(aws_creds_path))
        
        # Check ~/.aws/config
        aws_config_path = Path.home() / ".aws" / "config"
        if aws_config_path.exists():
            sources.append(str(aws_config_path))
        
        if sources:
            logger.info("AWS credentials detected", sources=sources)
            return {
                "detected": True,
                "sources": sources,
                "profile": self.AWS_PROFILE or os.environ.get("AWS_PROFILE", "default"),
                "region": self.AWS_DEFAULT_REGION or os.environ.get("AWS_DEFAULT_REGION")
            }
        
        return None
    
    def _detect_kubernetes_credentials(self) -> Optional[Dict[str, Any]]:
        """Detect Kubernetes credentials from standard locations."""
        kubeconfig_path = None
        
        # Check KUBECONFIG environment variable
        if self.KUBECONFIG:
            kubeconfig_path = Path(self.KUBECONFIG)
        elif os.environ.get("KUBECONFIG"):
            kubeconfig_path = Path(os.environ["KUBECONFIG"])
        else:
            # Check default location
            default_kubeconfig = Path.home() / ".kube" / "config"
            if default_kubeconfig.exists():
                kubeconfig_path = default_kubeconfig
        
        if kubeconfig_path and kubeconfig_path.exists():
            logger.info("Kubernetes credentials detected", path=str(kubeconfig_path))
            return {
                "detected": True,
                "path": str(kubeconfig_path),
                "source": "KUBECONFIG" if self.KUBECONFIG or os.environ.get("KUBECONFIG") else "~/.kube/config"
            }
        
        return None
    
    def _detect_ssh_config(self) -> Optional[Dict[str, Any]]:
        """Detect SSH configuration from standard locations."""
        ssh_config_path = Path.home() / ".ssh" / "config"
        
        if ssh_config_path.exists():
            logger.info("SSH config detected", path=str(ssh_config_path))
            return {
                "detected": True,
                "path": str(ssh_config_path)
            }
        
        return None
    
    def _detect_docker_config(self) -> Optional[Dict[str, Any]]:
        """Detect Docker configuration from standard locations."""
        docker_config_path = Path.home() / ".docker" / "config.json"
        
        if docker_config_path.exists():
            logger.info("Docker config detected", path=str(docker_config_path))
            return {
                "detected": True,
                "path": str(docker_config_path)
            }
        
        return None
    
    # -------------------------------------------------------------------------
    # Configuration source tracking
    # -------------------------------------------------------------------------
    
    def get_config_sources(self) -> Dict[str, str]:
        """
        Get the source of each configuration value.
        
        Returns:
            Dictionary mapping field name to source description.
        """
        sources = {}
        
        for field_name in self.model_fields.keys():
            value = getattr(self, field_name)
            
            # Check if value is from environment variable
            if os.environ.get(field_name) is not None:
                sources[field_name] = "environment variable"
            # Check if value is from .env file (non-default and not in env)
            elif value != self.model_fields[field_name].default:
                sources[field_name] = ".env file"
            # Check if it's a system-level credential
            elif field_name in ["AWS_PROFILE", "AWS_DEFAULT_REGION", "KUBECONFIG"]:
                if value:
                    sources[field_name] = "system config"
                else:
                    sources[field_name] = "default"
            else:
                sources[field_name] = "default"
        
        return sources
    
    def log_configuration_sources(self) -> None:
        """Log which configuration source is used for each value."""
        sources = self.get_config_sources()
        
        # Group by source
        by_source: Dict[str, list] = {}
        for field_name, source in sources.items():
            if source not in by_source:
                by_source[source] = []
            by_source[source].append(field_name)
        
        logger.info("Configuration loaded", sources=by_source)
        
        # Log detected system credentials
        system_creds = self.detect_system_credentials()
        if system_creds:
            logger.info("System-level credentials detected", credentials=list(system_creds.keys()))
    
    @staticmethod
    def mask_sensitive_value(value: str) -> str:
        """
        Mask sensitive values showing only first and last 4 characters.
        
        Args:
            value: The sensitive value to mask
            
        Returns:
            Masked value in format: "abcd****wxyz"
        """
        if not value or len(value) <= 8:
            return "****"
        return f"{value[:4]}****{value[-4:]}"
    
    def to_dict(self, mask_sensitive: bool = True) -> Dict[str, Any]:
        """
        Convert configuration to dictionary.
        
        Args:
            mask_sensitive: Whether to mask sensitive values (API keys, passwords)
            
        Returns:
            Dictionary representation of configuration
        """
        _SENSITIVE_KEYWORDS = ("KEY", "SECRET", "PASSWORD", "TOKEN", "CREDENTIAL")
        sensitive_fields = {
            name for name in self.model_fields.keys()
            if any(kw in name.upper() for kw in _SENSITIVE_KEYWORDS)
        }
        
        result = {}
        for field_name in self.model_fields.keys():
            value = getattr(self, field_name)
            
            if mask_sensitive and field_name in sensitive_fields and value:
                result[field_name] = self.mask_sensitive_value(str(value))
            else:
                result[field_name] = value
        
        return result


# Global configuration instance
_config: Optional[Config] = None


def get_config() -> Config:
    """
    Get the global configuration instance.
    
    Returns:
        Config instance
        
    Raises:
        RuntimeError: If configuration has not been initialized
    """
    global _config
    if _config is None:
        raise RuntimeError(
            "Configuration not initialized. Call load_config() first."
        )
    return _config


def _find_env_file() -> str:
    """Locate .env by walking up from CWD, then falling back to the package root."""
    # Walk up from CWD
    current = Path(".").resolve()
    for directory in [current] + list(current.parents):
        candidate = directory / ".env"
        if candidate.exists():
            return str(candidate)
    # Fallback: project root relative to this file (aise/core/config.py)
    project_root_env = Path(__file__).parent.parent.parent / ".env"
    if project_root_env.exists():
        return str(project_root_env)
    return ".env"


def load_config() -> Config:
    """
    Load and validate configuration from all sources.
    
    Returns:
        Validated Config instance
        
    Raises:
        ValidationError: If configuration is invalid
    """
    global _config
    
    try:
        env_file = _find_env_file()
        Config.model_config["env_file"] = env_file
        _config = Config()

        # Configure structured logging with settings from config
        from aise.core.logging import setup_logging
        setup_logging(
            log_level=_config.LOG_LEVEL,
            debug=_config.DEBUG,
            json_output=False,  # always human-readable on console; set True for container/prod
            enable_pii_redaction=True,
        )

        _config.log_configuration_sources()
        
        # Auto-configure LangSmith if API key is present
        if _config.LANGSMITH_API_KEY:
            from aise.observability.langsmith import configure_langsmith
            configure_langsmith(api_key=_config.LANGSMITH_API_KEY)
        
        return _config
    except Exception as e:
        logger.error("Failed to load configuration", error=str(e))
        raise
