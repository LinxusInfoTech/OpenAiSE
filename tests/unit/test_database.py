# tests/unit/test_database.py
"""Unit tests for DatabaseManager class."""

import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from aise.core.database import DatabaseManager, initialize_database, get_database, close_database
from aise.core.exceptions import ConfigurationError


@pytest.fixture
def mock_config():
    """Create a mock configuration."""
    config = Mock()
    config.POSTGRES_URL = "postgresql://user:pass@localhost/testdb"
    return config


@pytest.fixture
def mock_pool():
    """Create a mock asyncpg connection pool."""
    pool = AsyncMock()
    pool.get_size = Mock(return_value=10)
    pool.get_idle_size = Mock(return_value=5)
    pool.get_min_size = Mock(return_value=5)
    pool.get_max_size = Mock(return_value=20)
    
    # Mock connection context manager
    conn = AsyncMock()
    conn.fetchval = AsyncMock(return_value="PostgreSQL 16.0")
    conn.execute = AsyncMock()
    conn.fetch = AsyncMock(return_value=[])
    
    acquire_cm = AsyncMock()
    acquire_cm.__aenter__ = AsyncMock(return_value=conn)
    acquire_cm.__aexit__ = AsyncMock(return_value=None)
    pool.acquire = Mock(return_value=acquire_cm)
    pool.close = AsyncMock()
    
    return pool


class TestDatabaseManager:
    """Test suite for DatabaseManager class."""
    
    @pytest.mark.asyncio
    async def test_initialize_creates_pool(self, mock_config, mock_pool):
        """Test that initialization creates connection pool."""
        db = DatabaseManager(mock_config)
        
        with patch('aise.core.database.asyncpg.create_pool', new_callable=AsyncMock) as mock_cp:
            mock_cp.return_value = mock_pool
            with patch.object(db, '_initialize_schema', new_callable=AsyncMock):
                await db.initialize()
        
        assert db._pool is not None
    
    @pytest.mark.asyncio
    async def test_initialize_without_postgres_url_raises_error(self):
        """Test that initialization fails without POSTGRES_URL."""
        config = Mock()
        config.POSTGRES_URL = None
        
        db = DatabaseManager(config)
        
        with pytest.raises(ConfigurationError, match="POSTGRES_URL not configured"):
            await db.initialize()

    
    @pytest.mark.asyncio
    async def test_pool_property_raises_error_if_not_initialized(self, mock_config):
        """Test that accessing pool before initialization raises error."""
        db = DatabaseManager(mock_config)
        
        with pytest.raises(ConfigurationError, match="not initialized"):
            _ = db.pool
    
    @pytest.mark.asyncio
    async def test_health_check_returns_true_when_healthy(self, mock_config, mock_pool):
        """Test that health check returns True when database is healthy."""
        db = DatabaseManager(mock_config)
        db._pool = mock_pool
        
        result = await db.health_check()
        
        assert result is True
    
    @pytest.mark.asyncio
    async def test_health_check_returns_false_when_unhealthy(self, mock_config, mock_pool):
        """Test that health check returns False when database is unhealthy."""
        db = DatabaseManager(mock_config)
        db._pool = mock_pool
        
        # Make fetchval raise an exception
        conn = await mock_pool.acquire().__aenter__()
        conn.fetchval.side_effect = Exception("Connection failed")
        
        result = await db.health_check()
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_get_pool_stats_returns_stats(self, mock_config, mock_pool):
        """Test that get_pool_stats returns pool statistics."""
        db = DatabaseManager(mock_config)
        db._pool = mock_pool
        
        stats = await db.get_pool_stats()
        
        assert stats['initialized'] is True
        assert stats['size'] == 10
        assert stats['free'] == 5
        assert stats['min_size'] == 5
        assert stats['max_size'] == 20
    
    @pytest.mark.asyncio
    async def test_close_closes_pool(self, mock_config, mock_pool):
        """Test that close closes the connection pool."""
        db = DatabaseManager(mock_config)
        db._pool = mock_pool
        
        await db.close()
        
        mock_pool.close.assert_called_once()
        assert db._pool is None


class TestGlobalDatabaseFunctions:
    """Test suite for global database functions."""
    
    @pytest.mark.asyncio
    async def test_initialize_database_creates_manager(self, mock_config, mock_pool):
        """Test that initialize_database creates global manager."""
        with patch('aise.core.database.asyncpg.create_pool', new_callable=AsyncMock) as mock_cp:
            mock_cp.return_value = mock_pool
            with patch('aise.core.database.DatabaseManager._initialize_schema', new_callable=AsyncMock):
                db = await initialize_database(mock_config)
        
        assert db is not None
        assert isinstance(db, DatabaseManager)
        
        # Clean up
        await close_database()
    
    @pytest.mark.asyncio
    async def test_get_database_raises_error_if_not_initialized(self):
        """Test that get_database raises error if not initialized."""
        # Ensure database is closed
        await close_database()
        
        with pytest.raises(ConfigurationError, match="not initialized"):
            await get_database()
