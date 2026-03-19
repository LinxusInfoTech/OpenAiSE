# tests/unit/test_config_persistence.py
"""Unit tests for configuration persistence."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aise.config_ui.persistence import ConfigPersistence
from aise.core.exceptions import ConfigurationError


@pytest.fixture
def mock_config():
    """Create a mock configuration instance."""
    config = MagicMock(spec=[
        'POSTGRES_URL', 'ANTHROPIC_API_KEY', 'OPENAI_API_KEY',
        'LLM_PROVIDER', 'AISE_MODE', 'model_fields'
    ])
    config.POSTGRES_URL = "postgresql://user:pass@localhost/test"
    config.ANTHROPIC_API_KEY = None
    config.OPENAI_API_KEY = None
    config.LLM_PROVIDER = "anthropic"
    config.AISE_MODE = "approval"
    config.model_fields = {
        "ANTHROPIC_API_KEY": MagicMock(annotation=str),
        "LLM_PROVIDER": MagicMock(annotation=str),
        "AISE_MODE": MagicMock(annotation=str),
    }
    return config


@pytest.fixture
def mock_credential_storage():
    """Create a mock credential storage instance."""
    storage = AsyncMock()
    storage.store = AsyncMock()
    storage.retrieve = AsyncMock()
    storage.delete = AsyncMock()
    return storage


@pytest.fixture
async def persistence(mock_config, mock_credential_storage):
    """Create a ConfigPersistence instance with mocked dependencies."""
    with patch('aise.config_ui.persistence.asyncpg.create_pool', new_callable=AsyncMock) as mock_pool:
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()
        mock_conn.fetchrow = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[])

        mock_pool_instance = MagicMock()
        mock_pool_instance.acquire = MagicMock()
        mock_pool_instance.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool_instance.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
        mock_pool_instance.close = AsyncMock()

        # create_pool is now an AsyncMock, so awaiting it returns mock_pool_instance
        mock_pool.return_value = mock_pool_instance

        persistence = ConfigPersistence(mock_config, mock_credential_storage)
        await persistence.initialize()

        yield persistence


@pytest.mark.asyncio
async def test_initialize_creates_schema(mock_config, mock_credential_storage):
    """Test that initialize creates the database schema."""
    with patch('aise.config_ui.persistence.asyncpg.create_pool', new_callable=AsyncMock) as mock_pool:
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()

        mock_pool_instance = MagicMock()
        mock_pool_instance.acquire = MagicMock()
        mock_pool_instance.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool_instance.acquire.return_value.__aexit__ = AsyncMock(return_value=None)
        mock_pool.return_value = mock_pool_instance

        persistence = ConfigPersistence(mock_config, mock_credential_storage)
        await persistence.initialize()

        # Verify schema creation was called
        assert mock_conn.execute.call_count >= 2  # At least table and index creation


@pytest.mark.asyncio
async def test_update_config_sensitive_value(persistence, mock_credential_storage):
    """Test updating a sensitive configuration value."""
    await persistence.update_config("ANTHROPIC_API_KEY", "sk-ant-test-key")
    
    # Verify it was stored in credential vault
    mock_credential_storage.store.assert_called_once_with(
        key="ANTHROPIC_API_KEY",
        plaintext_value="sk-ant-test-key",
        credential_type="api_key",
        component="config_ui"
    )


@pytest.mark.asyncio
async def test_update_config_non_sensitive_value(persistence):
    """Test updating a non-sensitive configuration value."""
    with patch.object(persistence._pool, 'acquire') as mock_acquire:
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()
        mock_acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire.return_value.__aexit__ = AsyncMock()
        
        await persistence.update_config("LLM_PROVIDER", "openai")
        
        # Verify it was stored in database
        mock_conn.execute.assert_called_once()
        call_args = mock_conn.execute.call_args[0]
        assert "INSERT INTO config_settings" in call_args[0]
        assert call_args[1] == "LLM_PROVIDER"
        assert call_args[2] == "openai"


@pytest.mark.asyncio
async def test_update_config_invalid_key(persistence):
    """Test updating an invalid configuration key."""
    with pytest.raises(ValueError, match="Unknown configuration key"):
        await persistence.update_config("INVALID_KEY", "value")


@pytest.mark.asyncio
async def test_update_config_empty_value(persistence):
    """Test updating with empty value."""
    with pytest.raises(ValueError, match="cannot be empty"):
        await persistence.update_config("LLM_PROVIDER", "")


@pytest.mark.asyncio
async def test_apply_to_runtime(persistence):
    """Test that configuration changes are applied to runtime."""
    with patch.object(persistence._pool, 'acquire') as mock_acquire:
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()
        mock_acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire.return_value.__aexit__ = AsyncMock()
        
        await persistence.update_config("LLM_PROVIDER", "openai")
        
        # Verify config was updated
        assert persistence._config.LLM_PROVIDER == "openai"


@pytest.mark.asyncio
async def test_get_config_sensitive(persistence, mock_credential_storage):
    """Test retrieving a sensitive configuration value."""
    mock_credential_storage.retrieve.return_value = "sk-ant-test-key"
    
    value = await persistence.get_config("ANTHROPIC_API_KEY")
    
    assert value == "sk-ant-test-key"
    mock_credential_storage.retrieve.assert_called_once_with("ANTHROPIC_API_KEY")


@pytest.mark.asyncio
async def test_get_config_non_sensitive(persistence):
    """Test retrieving a non-sensitive configuration value."""
    with patch.object(persistence._pool, 'acquire') as mock_acquire:
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value={"value": "openai"})
        mock_acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire.return_value.__aexit__ = AsyncMock()
        
        value = await persistence.get_config("LLM_PROVIDER")
        
        assert value == "openai"


@pytest.mark.asyncio
async def test_load_all_config(persistence, mock_credential_storage):
    """Test loading all configuration values."""
    with patch.object(persistence._pool, 'acquire') as mock_acquire:
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[
            {"key": "LLM_PROVIDER", "value": "openai"},
            {"key": "AISE_MODE", "value": "autonomous"}
        ])
        mock_acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire.return_value.__aexit__ = AsyncMock()
        
        mock_credential_storage.retrieve.return_value = "sk-ant-test-key"
        
        config_dict = await persistence.load_all_config()
        
        assert "LLM_PROVIDER" in config_dict
        assert config_dict["LLM_PROVIDER"] == "openai"
        assert "AISE_MODE" in config_dict


@pytest.mark.asyncio
async def test_delete_config_sensitive(persistence, mock_credential_storage):
    """Test deleting a sensitive configuration value."""
    await persistence.delete_config("ANTHROPIC_API_KEY")
    
    mock_credential_storage.delete.assert_called_once_with("ANTHROPIC_API_KEY")


@pytest.mark.asyncio
async def test_delete_config_non_sensitive(persistence):
    """Test deleting a non-sensitive configuration value."""
    with patch.object(persistence._pool, 'acquire') as mock_acquire:
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()
        mock_acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_acquire.return_value.__aexit__ = AsyncMock()
        
        result = await persistence.delete_config("LLM_PROVIDER")
        
        assert result is True
        mock_conn.execute.assert_called_once()


@pytest.mark.asyncio
async def test_close(persistence):
    """Test closing the persistence connection pool."""
    with patch.object(persistence._pool, 'close') as mock_close:
        mock_close.return_value = None
        
        await persistence.close()
        
        mock_close.assert_called_once()
