# aise/core/database.py
"""Database connection management and schema initialization.

This module provides database connection pooling, schema initialization,
and migration support for AiSE.

Example usage:
    >>> from aise.core.database import DatabaseManager
    >>> from aise.core.config import get_config
    >>> 
    >>> config = get_config()
    >>> db = DatabaseManager(config)
    >>> await db.initialize()
    >>> 
    >>> # Use connection pool
    >>> async with db.pool.acquire() as conn:
    ...     result = await conn.fetch("SELECT * FROM credentials")
    >>> 
    >>> await db.close()
"""

import asyncpg
from typing import Optional
import structlog
from pathlib import Path

from aise.core.exceptions import ConfigurationError

logger = structlog.get_logger(__name__)


class DatabaseManager:
    """Manages database connections and schema initialization.
    
    This class provides connection pooling, schema initialization,
    and health checks for PostgreSQL.
    
    Attributes:
        _config: Configuration instance
        _pool: asyncpg connection pool
    
    Example:
        >>> db = DatabaseManager(config)
        >>> await db.initialize()
        >>> async with db.pool.acquire() as conn:
        ...     await conn.execute("SELECT 1")
        >>> await db.close()
    """
    
    def __init__(self, config):
        """Initialize database manager.
        
        Args:
            config: Configuration instance with database settings
        """
        self._config = config
        self._pool: Optional[asyncpg.Pool] = None
    
    @property
    def pool(self) -> asyncpg.Pool:
        """Get connection pool.
        
        Returns:
            asyncpg connection pool
        
        Raises:
            ConfigurationError: If pool not initialized
        """
        if not self._pool:
            raise ConfigurationError(
                "Database pool not initialized. Call initialize() first.",
                field="POSTGRES_URL"
            )
        return self._pool
    
    async def initialize(
        self,
        min_size: int = 5,
        max_size: int = 20,
        command_timeout: int = 60,
        max_retries: int = 3
    ) -> None:
        """Initialize database connection pool and schema.
        
        Creates connection pool with retry logic and initializes
        database schema if needed.
        
        Args:
            min_size: Minimum pool size (default: 5)
            max_size: Maximum pool size (default: 20)
            command_timeout: Command timeout in seconds (default: 60)
            max_retries: Maximum connection retry attempts (default: 3)
        
        Raises:
            ConfigurationError: If connection fails after retries
        """
        if not hasattr(self._config, 'POSTGRES_URL') or not self._config.POSTGRES_URL:
            raise ConfigurationError(
                "POSTGRES_URL not configured",
                field="POSTGRES_URL"
            )
        
        # Try to connect with exponential backoff
        retry_count = 0
        last_error = None
        
        while retry_count < max_retries:
            try:
                self._pool = await asyncpg.create_pool(
                    self._config.POSTGRES_URL,
                    min_size=min_size,
                    max_size=max_size,
                    command_timeout=command_timeout
                )
                
                logger.info(
                    "database_pool_created",
                    min_size=min_size,
                    max_size=max_size,
                    command_timeout=command_timeout
                )
                
                # Verify connection
                async with self._pool.acquire() as conn:
                    version = await conn.fetchval("SELECT version()")
                    logger.info("database_connected", version=version)
                
                # Initialize schema
                await self._initialize_schema()
                
                logger.info("database_manager_initialized")
                return
                
            except Exception as e:
                last_error = e
                retry_count += 1
                
                if retry_count < max_retries:
                    wait_time = 2 ** retry_count  # Exponential backoff
                    logger.warning(
                        "database_connection_failed_retrying",
                        error=str(e),
                        retry=retry_count,
                        max_retries=max_retries,
                        wait_time=wait_time
                    )
                    import asyncio
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(
                        "database_connection_failed",
                        error=str(e),
                        retries=retry_count
                    )
        
        raise ConfigurationError(
            f"Failed to connect to database after {max_retries} attempts: {str(last_error)}",
            field="POSTGRES_URL"
        )
    
    async def _initialize_schema(self) -> None:
        """Initialize database schema if not exists.
        
        Runs the init-db.sql script to create tables and indexes.
        This is idempotent - safe to run multiple times.
        """
        try:
            # Read schema file
            schema_file = Path(__file__).parent.parent.parent / "scripts" / "init-db.sql"
            
            if not schema_file.exists():
                logger.warning(
                    "schema_file_not_found",
                    path=str(schema_file),
                    message="Skipping schema initialization"
                )
                return
            
            schema_sql = schema_file.read_text()
            
            # Execute schema
            async with self._pool.acquire() as conn:
                await conn.execute(schema_sql)
            
            logger.info("database_schema_initialized")
            
        except Exception as e:
            logger.error(
                "schema_initialization_failed",
                error=str(e)
            )
            # Don't raise - schema might already exist
    
    async def health_check(self) -> bool:
        """Check database connectivity.
        
        Returns:
            True if database is healthy, False otherwise
        """
        if not self._pool:
            return False
        
        try:
            async with self._pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return True
        except Exception as e:
            logger.error("database_health_check_failed", error=str(e))
            return False

    async def reconnect(self, max_retries: int = 3) -> bool:
        """Attempt to reconnect to the database.

        Closes the existing pool (if any) and re-initializes with
        exponential backoff.  Useful when the pool becomes stale after
        a network partition.

        Args:
            max_retries: Maximum reconnection attempts

        Returns:
            True if reconnection succeeded, False otherwise
        """
        logger.warning("database_reconnecting", max_retries=max_retries)
        try:
            if self._pool:
                await self._pool.close()
                self._pool = None
            await self.initialize(max_retries=max_retries)
            logger.info("database_reconnected")
            return True
        except Exception as exc:
            logger.error("database_reconnect_failed", error=str(exc))
            return False
    
    async def get_pool_stats(self) -> dict:
        """Get connection pool statistics.
        
        Returns:
            Dictionary with pool statistics
        """
        if not self._pool:
            return {
                "initialized": False
            }
        
        return {
            "initialized": True,
            "size": self._pool.get_size(),
            "free": self._pool.get_idle_size(),
            "min_size": self._pool.get_min_size(),
            "max_size": self._pool.get_max_size()
        }
    
    async def close(self) -> None:
        """Close database connection pool.
        
        Should be called during application shutdown.
        """
        if self._pool:
            await self._pool.close()
            logger.info("database_pool_closed")
            self._pool = None


# Global database manager instance
_db_manager: Optional[DatabaseManager] = None


async def get_database() -> DatabaseManager:
    """Get global database manager instance.
    
    Returns:
        DatabaseManager instance
    
    Raises:
        ConfigurationError: If database not initialized
    
    Example:
        >>> db = await get_database()
        >>> async with db.pool.acquire() as conn:
        ...     result = await conn.fetch("SELECT * FROM credentials")
    """
    global _db_manager
    
    if _db_manager is None:
        raise ConfigurationError(
            "Database not initialized. Call initialize_database() first.",
            field="POSTGRES_URL"
        )
    
    return _db_manager


async def initialize_database(config) -> DatabaseManager:
    """Initialize global database manager.
    
    Args:
        config: Configuration instance
    
    Returns:
        DatabaseManager instance
    
    Example:
        >>> from aise.core.config import get_config
        >>> config = get_config()
        >>> db = await initialize_database(config)
    """
    global _db_manager
    
    if _db_manager is None:
        _db_manager = DatabaseManager(config)
        await _db_manager.initialize()
    
    return _db_manager


async def close_database() -> None:
    """Close global database manager.
    
    Should be called during application shutdown.
    """
    global _db_manager
    
    if _db_manager:
        await _db_manager.close()
        _db_manager = None
