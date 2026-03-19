# tests/unit/test_config.py
"""Unit tests for configuration management."""

import os
import pytest
from pathlib import Path
from unittest.mock import patch
from pydantic import ValidationError
from aise.core.config import Config, load_config, get_config


class TestConfigValidation:
    """Test configuration validation."""
    
    def test_config_requires_postgres_url(self, monkeypatch):
        """Test that POSTGRES_URL is required."""
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.delenv("POSTGRES_URL", raising=False)

        with patch('aise.core.config.Config.model_config', new={'env_file': None, 'env_file_encoding': 'utf-8', 'extra': 'ignore'}):
            with pytest.raises(ValidationError) as exc_info:
                Config(_env_file=None)

        assert "POSTGRES_URL" in str(exc_info.value)

    def test_config_requires_redis_url(self, monkeypatch):
        """Test that REDIS_URL is required."""
        monkeypatch.setenv("POSTGRES_URL", "postgresql://localhost:5432/aise")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.delenv("REDIS_URL", raising=False)

        with patch('aise.core.config.Config.model_config', new={'env_file': None, 'env_file_encoding': 'utf-8', 'extra': 'ignore'}):
            with pytest.raises(ValidationError) as exc_info:
                Config(_env_file=None)

        assert "REDIS_URL" in str(exc_info.value)
    
    def test_config_requires_llm_provider_key(self, monkeypatch):
        """Test that at least one LLM provider API key is required."""
        monkeypatch.setenv("POSTGRES_URL", "postgresql://localhost:5432/aise")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        monkeypatch.setenv("LLM_PROVIDER", "anthropic")
        
        with pytest.raises(ValidationError) as exc_info:
            Config()
        
        assert "anthropic" in str(exc_info.value).lower()
    
    def test_config_validates_postgres_url_format(self, monkeypatch):
        """Test that POSTGRES_URL must have correct format."""
        monkeypatch.setenv("POSTGRES_URL", "invalid://localhost:5432/aise")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        
        with pytest.raises(ValidationError) as exc_info:
            Config()
        
        assert "postgresql://" in str(exc_info.value)
    
    def test_config_validates_redis_url_format(self, monkeypatch):
        """Test that REDIS_URL must have correct format."""
        monkeypatch.setenv("POSTGRES_URL", "postgresql://localhost:5432/aise")
        monkeypatch.setenv("REDIS_URL", "invalid://localhost:6379/0")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        
        with pytest.raises(ValidationError) as exc_info:
            Config()
        
        assert "redis://" in str(exc_info.value)
    
    def test_config_validates_embedding_model_requires_openai_key(self, monkeypatch):
        """Test that OpenAI embedding model requires OpenAI API key."""
        monkeypatch.setenv("POSTGRES_URL", "postgresql://localhost:5432/aise")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.setenv("EMBEDDING_MODEL", "openai")
        
        with pytest.raises(ValidationError) as exc_info:
            Config()
        
        assert "OPENAI_API_KEY" in str(exc_info.value)


class TestConfigDefaults:
    """Test configuration default values."""
    
    def test_config_has_correct_defaults(self, monkeypatch):
        """Test that configuration has correct default values."""
        monkeypatch.setenv("POSTGRES_URL", "postgresql://localhost:5432/aise")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
        monkeypatch.setenv("LLM_PROVIDER", "anthropic")
        monkeypatch.setenv("AISE_MODE", "approval")
        monkeypatch.setenv("EMBEDDING_MODEL", "openai")
        
        config = Config(_env_file=None)
        
        assert config.LLM_PROVIDER == "anthropic"
        assert config.AISE_MODE == "approval"
        assert config.CHROMA_HOST == "localhost"
        assert config.CHROMA_PORT == 8000
        assert config.OLLAMA_BASE_URL == "http://localhost:11434"
        assert config.USE_BROWSER_FALLBACK is False
        assert config.BROWSER_HEADLESS is True
        assert config.TOOL_EXECUTION_TIMEOUT == 30
        assert config.MAX_CONCURRENT_TOOLS == 5
        assert config.EMBEDDING_MODEL == "openai"
        assert config.CHUNK_SIZE == 1000
        assert config.CHUNK_OVERLAP == 150
        assert config.LOG_LEVEL == "INFO"
        assert config.DEBUG is False


class TestConfigOllamaProvider:
    """Test Ollama provider configuration."""
    
    def test_ollama_provider_does_not_require_api_key(self, monkeypatch):
        """Test that Ollama provider doesn't require API key."""
        monkeypatch.setenv("POSTGRES_URL", "postgresql://localhost:5432/aise")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        monkeypatch.setenv("LLM_PROVIDER", "ollama")
        monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
        
        config = Config()
        
        assert config.LLM_PROVIDER == "ollama"
        assert config.OLLAMA_BASE_URL == "http://localhost:11434"


class TestConfigSensitiveValueMasking:
    """Test masking of sensitive configuration values."""
    
    def test_mask_sensitive_value_short_string(self):
        """Test masking of short strings."""
        assert Config.mask_sensitive_value("short") == "****"
    
    def test_mask_sensitive_value_long_string(self):
        """Test masking of long strings."""
        masked = Config.mask_sensitive_value("abcdefghijklmnop")
        assert masked == "abcd****mnop"
        assert "efghijkl" not in masked
    
    def test_to_dict_masks_sensitive_fields(self, monkeypatch):
        """Test that to_dict masks sensitive fields by default."""
        monkeypatch.setenv("POSTGRES_URL", "postgresql://localhost:5432/aise")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-1234567890abcdef")
        
        config = Config()
        config_dict = config.to_dict(mask_sensitive=True)
        
        assert config_dict["ANTHROPIC_API_KEY"] == "sk-a****cdef"
        assert "1234567890" not in config_dict["ANTHROPIC_API_KEY"]
    
    def test_to_dict_reveals_sensitive_fields_when_requested(self, monkeypatch):
        """Test that to_dict can reveal sensitive fields."""
        monkeypatch.setenv("POSTGRES_URL", "postgresql://localhost:5432/aise")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-1234567890abcdef")
        
        config = Config()
        config_dict = config.to_dict(mask_sensitive=False)
        
        assert config_dict["ANTHROPIC_API_KEY"] == "sk-ant-1234567890abcdef"


class TestConfigSourceTracking:
    """Test configuration source tracking."""
    
    def test_get_config_sources_identifies_env_vars(self, monkeypatch):
        """Test that get_config_sources identifies environment variables."""
        monkeypatch.setenv("POSTGRES_URL", "postgresql://localhost:5432/aise")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        
        config = Config()
        sources = config.get_config_sources()
        
        assert sources["POSTGRES_URL"] == "environment variable"
        assert sources["REDIS_URL"] == "environment variable"
        assert sources["ANTHROPIC_API_KEY"] == "environment variable"
        assert sources["LOG_LEVEL"] == "environment variable"
    
    def test_get_config_sources_identifies_defaults(self, monkeypatch):
        """Test that get_config_sources identifies default values."""
        monkeypatch.setenv("POSTGRES_URL", "postgresql://localhost:5432/aise")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
        monkeypatch.delenv("AISE_MODE", raising=False)
        monkeypatch.delenv("LLM_PROVIDER", raising=False)

        config = Config(_env_file=None)
        sources = config.get_config_sources()

        assert sources["CHROMA_HOST"] == "default"
        assert sources["CHROMA_PORT"] == "default"
        assert sources["AISE_MODE"] == "default"


class TestSystemCredentialDetection:
    """Test system-level credential detection."""
    
    def test_detect_aws_credentials_from_env(self, monkeypatch):
        """Test AWS credential detection from environment variables."""
        monkeypatch.setenv("POSTGRES_URL", "postgresql://localhost:5432/aise")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test-access-key")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test-secret-key")
        
        config = Config()
        aws_creds = config._detect_aws_credentials()
        
        assert aws_creds is not None
        assert aws_creds["detected"] is True
        assert "environment variables" in aws_creds["sources"]
    
    def test_detect_aws_credentials_from_profile(self, monkeypatch):
        """Test AWS credential detection from profile."""
        monkeypatch.setenv("POSTGRES_URL", "postgresql://localhost:5432/aise")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.setenv("AWS_PROFILE", "production")
        
        config = Config()
        aws_creds = config._detect_aws_credentials()
        
        assert aws_creds is not None
        assert aws_creds["detected"] is True
        assert aws_creds["profile"] == "production"
    
    def test_detect_kubernetes_credentials_from_env(self, monkeypatch, tmp_path):
        """Test Kubernetes credential detection from KUBECONFIG."""
        kubeconfig_file = tmp_path / "kubeconfig"
        kubeconfig_file.write_text("apiVersion: v1\nkind: Config")
        
        monkeypatch.setenv("POSTGRES_URL", "postgresql://localhost:5432/aise")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.setenv("KUBECONFIG", str(kubeconfig_file))
        
        config = Config()
        kube_creds = config._detect_kubernetes_credentials()
        
        assert kube_creds is not None
        assert kube_creds["detected"] is True
        assert kube_creds["source"] == "KUBECONFIG"
    
    def test_detect_ssh_config(self, monkeypatch, tmp_path):
        """Test SSH config detection."""
        # Create a temporary home directory with SSH config
        ssh_dir = tmp_path / ".ssh"
        ssh_dir.mkdir()
        ssh_config = ssh_dir / "config"
        ssh_config.write_text("Host example\n  HostName example.com")
        
        monkeypatch.setenv("POSTGRES_URL", "postgresql://localhost:5432/aise")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.setenv("HOME", str(tmp_path))
        
        config = Config()
        ssh_creds = config._detect_ssh_config()
        
        assert ssh_creds is not None
        assert ssh_creds["detected"] is True
    
    def test_detect_docker_config(self, monkeypatch, tmp_path):
        """Test Docker config detection."""
        # Create a temporary home directory with Docker config
        docker_dir = tmp_path / ".docker"
        docker_dir.mkdir()
        docker_config = docker_dir / "config.json"
        docker_config.write_text('{"auths": {}}')
        
        monkeypatch.setenv("POSTGRES_URL", "postgresql://localhost:5432/aise")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        monkeypatch.setenv("HOME", str(tmp_path))
        
        config = Config()
        docker_creds = config._detect_docker_config()
        
        assert docker_creds is not None
        assert docker_creds["detected"] is True


class TestConfigGlobalInstance:
    """Test global configuration instance management."""
    
    def test_get_config_raises_before_load(self):
        """Test that get_config raises error before load_config is called."""
        # Reset global config
        import aise.core.config as config_module
        config_module._config = None
        
        with pytest.raises(RuntimeError) as exc_info:
            get_config()
        
        assert "not initialized" in str(exc_info.value).lower()
    
    def test_load_config_returns_config_instance(self, monkeypatch):
        """Test that load_config returns a Config instance."""
        monkeypatch.setenv("POSTGRES_URL", "postgresql://localhost:5432/aise")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        
        config = load_config()
        
        assert isinstance(config, Config)
        assert config.POSTGRES_URL == "postgresql://localhost:5432/aise"
    
    def test_get_config_returns_loaded_config(self, monkeypatch):
        """Test that get_config returns the loaded configuration."""
        monkeypatch.setenv("POSTGRES_URL", "postgresql://localhost:5432/aise")
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
        
        load_config()
        config = get_config()
        
        assert isinstance(config, Config)
        assert config.POSTGRES_URL == "postgresql://localhost:5432/aise"
