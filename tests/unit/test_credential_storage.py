# tests/unit/test_credential_storage.py
"""Unit tests for CredentialStorage class."""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime
from cryptography.fernet import Fernet

from aise.core.credential_storage import CredentialStorage
from aise.core.credential_vault import CredentialVault
from aise.core.exceptions import CredentialVaultError, ConfigurationError


@pytest.fixture
def mock_config():
    """Create a mock configuration."""
    config = Mock()
    config.DATABASE_URL = "postgresql://user:pass@localhost/testdb"
    config.CREDENTIAL_VAULT_KEY = Fernet.generate_key().decode('utf-8')
    return config


@pytest.fixture
def vault(mock_config):
    """Create a CredentialVault instance."""
    return CredentialVault(mock_config)


@pytest.fixture
def mock_pool():
    """Create a mock asyncpg connection pool."""
    pool = AsyncMock()
    
    # Mock connection context manager
    conn = AsyncMock()
    conn.execute = AsyncMock()
    conn.fetchrow = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    
    # Mock acquire context manager
    acquire_cm = AsyncMock()
    acquire_cm.__aenter__ = AsyncMock(return_value=conn)
    acquire_cm.__aexit__ = AsyncMock(return_value=None)
    pool.acquire = Mock(return_value=acquire_cm)
    pool.close = AsyncMock()
    
    return pool


class TestCredentialStorageInitialization:
    """Test suite for CredentialStorage initialization."""
    
    @pytest.mark.asyncio
    async def test_initialize_creates_pool_and_schema(self, mock_config, vault):
        """Test that initialization creates connection pool and schema."""
        storage = CredentialStorage(mock_config, vault)
        
        with patch('aise.core.credential_storage.asyncpg.create_pool', new_callable=AsyncMock) as mock_create_pool:
            mock_pool = MagicMock()
            mock_conn = AsyncMock()
            mock_conn.execute = AsyncMock()

            acquire_cm = AsyncMock()
            acquire_cm.__aenter__ = AsyncMock(return_value=mock_conn)
            acquire_cm.__aexit__ = AsyncMock(return_value=None)
            mock_pool.acquire = Mock(return_value=acquire_cm)

            mock_create_pool.return_value = mock_pool

            await storage.initialize()

            # Verify pool created with correct parameters
            mock_create_pool.assert_called_once_with(
                mock_config.DATABASE_URL,
                min_size=5,
                max_size=20,
                command_timeout=60
            )

            # Verify schema creation was called
            assert mock_conn.execute.call_count >= 4  # At least 4 SQL statements
    
    @pytest.mark.asyncio
    async def test_initialize_without_database_url_raises_error(self, vault):
        """Test that initialization fails without DATABASE_URL."""
        config = Mock()
        config.DATABASE_URL = None
        config.POSTGRES_URL = None

        storage = CredentialStorage(config, vault)

        with pytest.raises(ConfigurationError):
            await storage.initialize()
    
    @pytest.mark.asyncio
    async def test_initialize_with_connection_failure_raises_error(self, mock_config, vault):
        """Test that initialization fails gracefully on connection error."""
        storage = CredentialStorage(mock_config, vault)
        
        with patch('aise.core.credential_storage.asyncpg.create_pool', new_callable=AsyncMock) as mock_create_pool:
            mock_create_pool.side_effect = Exception("Connection refused")
            
            with pytest.raises(ConfigurationError, match="Failed to initialize"):
                await storage.initialize()


class TestCredentialStorageStore:
    """Test suite for storing credentials."""
    
    @pytest.mark.asyncio
    async def test_store_encrypts_and_saves_credential(self, mock_config, vault, mock_pool):
        """Test that store encrypts and saves credential to database."""
        storage = CredentialStorage(mock_config, vault)
        storage._pool = mock_pool
        
        result = await storage.store("test_key", "test_value", "api_key")
        
        assert result is True
        
        # Verify database insert was called
        conn = await mock_pool.acquire().__aenter__()
        conn.execute.assert_called()

        # Verify the SQL contains INSERT INTO credentials (check all calls)
        all_sqls = [call[0][0] for call in conn.execute.call_args_list if call[0]]
        assert any("INSERT INTO credentials" in sql for sql in all_sqls)
    
    @pytest.mark.asyncio
    async def test_store_empty_key_raises_error(self, mock_config, vault, mock_pool):
        """Test that storing with empty key raises ValueError."""
        storage = CredentialStorage(mock_config, vault)
        storage._pool = mock_pool
        
        with pytest.raises(ValueError, match="key and value cannot be empty"):
            await storage.store("", "value")
    
    @pytest.mark.asyncio
    async def test_store_empty_value_raises_error(self, mock_config, vault, mock_pool):
        """Test that storing with empty value raises ValueError."""
        storage = CredentialStorage(mock_config, vault)
        storage._pool = mock_pool
        
        with pytest.raises(ValueError, match="key and value cannot be empty"):
            await storage.store("key", "")
    
    @pytest.mark.asyncio
    async def test_store_without_initialization_raises_error(self, mock_config, vault):
        """Test that store fails if not initialized."""
        storage = CredentialStorage(mock_config, vault)
        
        with pytest.raises(CredentialVaultError, match="not initialized"):
            await storage.store("key", "value")
    
    @pytest.mark.asyncio
    async def test_store_updates_existing_credential(self, mock_config, vault, mock_pool):
        """Test that store updates existing credential (upsert)."""
        storage = CredentialStorage(mock_config, vault)
        storage._pool = mock_pool
        
        # Store twice with same key
        await storage.store("test_key", "value1")
        await storage.store("test_key", "value2")
        
        # Verify both calls succeeded
        conn = await mock_pool.acquire().__aenter__()
        assert conn.execute.call_count >= 2


class TestCredentialStorageRetrieve:
    """Test suite for retrieving credentials."""
    
    @pytest.mark.asyncio
    async def test_retrieve_decrypts_and_returns_credential(self, mock_config, vault, mock_pool):
        """Test that retrieve decrypts and returns credential."""
        storage = CredentialStorage(mock_config, vault)
        storage._pool = mock_pool
        
        # First store a credential
        plaintext = "my-secret-value"
        encrypted = vault.encrypt(plaintext)
        
        # Mock database return
        conn = await mock_pool.acquire().__aenter__()
        conn.fetchrow.return_value = {
            'encrypted_value': encrypted,
            'credential_type': 'api_key'
        }
        
        # Retrieve
        result = await storage.retrieve("test_key")
        
        assert result == plaintext
        
        # Verify database query was called
        conn.fetchrow.assert_called()
        call_args = conn.fetchrow.call_args[0]
        assert "SELECT encrypted_value" in call_args[0]
    
    @pytest.mark.asyncio
    async def test_retrieve_nonexistent_key_returns_none(self, mock_config, vault, mock_pool):
        """Test that retrieving nonexistent key returns None."""
        storage = CredentialStorage(mock_config, vault)
        storage._pool = mock_pool
        
        # Mock database return None
        conn = await mock_pool.acquire().__aenter__()
        conn.fetchrow.return_value = None
        
        result = await storage.retrieve("nonexistent_key")
        
        assert result is None
    
    @pytest.mark.asyncio
    async def test_retrieve_empty_key_raises_error(self, mock_config, vault, mock_pool):
        """Test that retrieving with empty key raises ValueError."""
        storage = CredentialStorage(mock_config, vault)
        storage._pool = mock_pool
        
        with pytest.raises(ValueError, match="key cannot be empty"):
            await storage.retrieve("")
    
    @pytest.mark.asyncio
    async def test_retrieve_without_initialization_raises_error(self, mock_config, vault):
        """Test that retrieve fails if not initialized."""
        storage = CredentialStorage(mock_config, vault)
        
        with pytest.raises(CredentialVaultError, match="not initialized"):
            await storage.retrieve("key")
    
    @pytest.mark.asyncio
    async def test_retrieve_updates_access_tracking(self, mock_config, vault, mock_pool):
        """Test that retrieve updates accessed_at and access_count."""
        storage = CredentialStorage(mock_config, vault)
        storage._pool = mock_pool
        
        # Mock database return
        encrypted = vault.encrypt("test-value")
        conn = await mock_pool.acquire().__aenter__()
        conn.fetchrow.return_value = {
            'encrypted_value': encrypted,
            'credential_type': 'api_key'
        }
        
        await storage.retrieve("test_key")
        
        # Verify UPDATE was called for access tracking
        assert conn.execute.call_count >= 1
        update_call = [call for call in conn.execute.call_args_list 
                      if 'UPDATE credentials' in str(call)]
        assert len(update_call) > 0


class TestCredentialStorageDelete:
    """Test suite for deleting credentials."""
    
    @pytest.mark.asyncio
    async def test_delete_removes_credential(self, mock_config, vault, mock_pool):
        """Test that delete removes credential from database."""
        storage = CredentialStorage(mock_config, vault)
        storage._pool = mock_pool
        
        # Mock successful deletion
        conn = await mock_pool.acquire().__aenter__()
        conn.execute.return_value = "DELETE 1"
        
        result = await storage.delete("test_key")
        
        assert result is True
        
        # Verify DELETE was called
        conn.execute.assert_called()
        all_sqls = [call[0][0] for call in conn.execute.call_args_list if call[0]]
        assert any("DELETE FROM credentials" in sql for sql in all_sqls)
    
    @pytest.mark.asyncio
    async def test_delete_nonexistent_key_returns_false(self, mock_config, vault, mock_pool):
        """Test that deleting nonexistent key returns False."""
        storage = CredentialStorage(mock_config, vault)
        storage._pool = mock_pool
        
        # Mock no rows deleted
        conn = await mock_pool.acquire().__aenter__()
        conn.execute.return_value = "DELETE 0"
        
        result = await storage.delete("nonexistent_key")
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_delete_empty_key_raises_error(self, mock_config, vault, mock_pool):
        """Test that deleting with empty key raises ValueError."""
        storage = CredentialStorage(mock_config, vault)
        storage._pool = mock_pool
        
        with pytest.raises(ValueError, match="key cannot be empty"):
            await storage.delete("")


class TestCredentialStorageListKeys:
    """Test suite for listing credential keys."""
    
    @pytest.mark.asyncio
    async def test_list_keys_returns_metadata(self, mock_config, vault, mock_pool):
        """Test that list_keys returns credential metadata."""
        storage = CredentialStorage(mock_config, vault)
        storage._pool = mock_pool
        
        # Mock database return
        conn = await mock_pool.acquire().__aenter__()
        conn.fetch.return_value = [
            {
                'key': 'key1',
                'credential_type': 'api_key',
                'created_at': datetime.now(),
                'updated_at': datetime.now(),
                'accessed_at': datetime.now(),
                'access_count': 5
            },
            {
                'key': 'key2',
                'credential_type': 'password',
                'created_at': datetime.now(),
                'updated_at': datetime.now(),
                'accessed_at': None,
                'access_count': 0
            }
        ]
        
        result = await storage.list_keys()
        
        assert len(result) == 2
        assert result[0]['key'] == 'key1'
        assert result[1]['key'] == 'key2'
        
        # Verify SELECT was called
        conn.fetch.assert_called()
    
    @pytest.mark.asyncio
    async def test_list_keys_empty_database_returns_empty_list(self, mock_config, vault, mock_pool):
        """Test that list_keys returns empty list when no credentials."""
        storage = CredentialStorage(mock_config, vault)
        storage._pool = mock_pool
        
        # Mock empty database
        conn = await mock_pool.acquire().__aenter__()
        conn.fetch.return_value = []
        
        result = await storage.list_keys()
        
        assert result == []


class TestCredentialStorageRotateKey:
    """Test suite for rotating credentials."""
    
    @pytest.mark.asyncio
    async def test_rotate_key_updates_credential(self, mock_config, vault, mock_pool):
        """Test that rotate_key updates credential with new value."""
        storage = CredentialStorage(mock_config, vault)
        storage._pool = mock_pool
        
        # Mock existing credential
        conn = await mock_pool.acquire().__aenter__()
        conn.fetchrow.return_value = {'credential_type': 'api_key'}
        
        result = await storage.rotate_key("test_key", "new-value")
        
        assert result is True
        
        # Verify INSERT (upsert) was called
        assert conn.execute.call_count >= 1


class TestCredentialStorageAuditLog:
    """Test suite for audit logging."""
    
    @pytest.mark.asyncio
    async def test_get_audit_log_returns_entries(self, mock_config, vault, mock_pool):
        """Test that get_audit_log returns audit entries."""
        storage = CredentialStorage(mock_config, vault)
        storage._pool = mock_pool
        
        # Mock audit log entries
        conn = await mock_pool.acquire().__aenter__()
        conn.fetch.return_value = [
            {
                'credential_key': 'test_key',
                'operation': 'store',
                'component': 'system',
                'timestamp': datetime.now(),
                'success': True,
                'error_message': None
            }
        ]
        
        result = await storage.get_audit_log()
        
        assert len(result) == 1
        assert result[0]['credential_key'] == 'test_key'
        assert result[0]['operation'] == 'store'
    
    @pytest.mark.asyncio
    async def test_get_audit_log_filters_by_key(self, mock_config, vault, mock_pool):
        """Test that get_audit_log can filter by credential key."""
        storage = CredentialStorage(mock_config, vault)
        storage._pool = mock_pool
        
        conn = await mock_pool.acquire().__aenter__()
        conn.fetch.return_value = []
        
        await storage.get_audit_log(credential_key="specific_key", limit=50)
        
        # Verify WHERE clause was used
        call_args = conn.fetch.call_args[0]
        assert "WHERE credential_key" in call_args[0]


class TestCredentialStorageClose:
    """Test suite for closing storage."""
    
    @pytest.mark.asyncio
    async def test_close_closes_pool(self, mock_config, vault, mock_pool):
        """Test that close closes the connection pool."""
        storage = CredentialStorage(mock_config, vault)
        storage._pool = mock_pool
        
        await storage.close()
        
        mock_pool.close.assert_called_once()
