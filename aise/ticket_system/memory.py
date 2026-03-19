# aise/ticket_system/memory.py
"""
Conversation memory with PostgreSQL and Redis caching.

This module provides conversation history management for ticket threads,
with PostgreSQL for persistent storage and Redis for fast access to recent messages.
"""

import json
from typing import List, Optional
from datetime import datetime, timedelta
import structlog
import redis.asyncio as redis
import asyncpg
from aise.observability.metrics import record_cache_op

from aise.ticket_system.base import Message
from aise.core.exceptions import DatabaseError

logger = structlog.get_logger(__name__)


class ConversationMemory:
    """Manages conversation history across ticket interactions.
    
    Stores all messages in PostgreSQL for persistence and caches recent
    messages in Redis for fast access. Implements automatic data retention
    policies and graceful fallback when Redis is unavailable.
    
    Attributes:
        postgres: asyncpg connection pool
        redis: Redis client
        retention_days: Number of days to retain conversations (default: 90)
        cache_size: Number of recent messages to cache per ticket (default: 10)
    
    Example:
        >>> memory = ConversationMemory(postgres_pool, redis_client)
        >>> message = Message(
        ...     id="msg_123",
        ...     author="user@example.com",
        ...     body="Hello, I need help",
        ...     is_customer=True,
        ...     created_at=datetime.utcnow()
        ... )
        >>> await memory.store_message("ticket_123", message)
        >>> thread = await memory.get_thread("ticket_123")
    """
    
    def __init__(
        self,
        postgres_pool: asyncpg.Pool,
        redis_client: redis.Redis,
        retention_days: int = 90,
        cache_size: int = 10
    ):
        """Initialize conversation memory.
        
        Args:
            postgres_pool: asyncpg connection pool
            redis_client: Redis client
            retention_days: Days to retain conversations (default: 90)
            cache_size: Number of messages to cache per ticket (default: 10)
        """
        self.postgres = postgres_pool
        self.redis = redis_client
        self.retention_days = retention_days
        self.cache_size = cache_size
        
        logger.info(
            "conversation_memory_initialized",
            retention_days=retention_days,
            cache_size=cache_size
        )
    
    async def store_message(
        self,
        ticket_id: str,
        message: Message
    ) -> None:
        """Store message in conversation history.
        
        Persists message to PostgreSQL and updates Redis cache.
        If Redis is unavailable, continues with PostgreSQL only.
        
        Args:
            ticket_id: Unique ticket identifier
            message: Message to store
        
        Raises:
            DatabaseError: If PostgreSQL storage fails
        """
        try:
            # Store in PostgreSQL
            async with self.postgres.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO conversation_memory 
                    (ticket_id, message_id, author, body, is_customer, created_at, metadata)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ON CONFLICT (message_id) DO UPDATE
                    SET body = EXCLUDED.body,
                        author = EXCLUDED.author,
                        is_customer = EXCLUDED.is_customer
                    """,
                    ticket_id,
                    message.id,
                    message.author,
                    message.body,
                    message.is_customer,
                    message.created_at,
                    json.dumps({})  # Empty metadata for now
                )
            
            logger.info(
                "message_stored_postgres",
                ticket_id=ticket_id,
                message_id=message.id,
                is_customer=message.is_customer
            )
            
            # Update Redis cache
            try:
                await self._update_redis_cache(ticket_id, message)
            except Exception as e:
                logger.warning(
                    "redis_cache_update_failed",
                    ticket_id=ticket_id,
                    error=str(e),
                    message="Continuing with PostgreSQL only"
                )
        
        except Exception as e:
            logger.error(
                "message_storage_failed",
                ticket_id=ticket_id,
                message_id=message.id,
                error=str(e)
            )
            raise DatabaseError(
                f"Failed to store message: {str(e)}",
                operation="store_message"
            )
    
    async def _update_redis_cache(
        self,
        ticket_id: str,
        message: Message
    ) -> None:
        """Update Redis cache with new message.
        
        Maintains a list of recent messages per ticket, limited by cache_size.
        Invalidates cache when new message is added.
        
        Args:
            ticket_id: Unique ticket identifier
            message: Message to cache
        """
        cache_key = f"conversation:{ticket_id}"
        
        # Serialize message
        message_data = {
            "id": message.id,
            "author": message.author,
            "body": message.body,
            "is_customer": message.is_customer,
            "created_at": message.created_at.isoformat()
        }
        
        # Add to list (right push)
        await self.redis.rpush(cache_key, json.dumps(message_data))
        
        # Trim to keep only recent messages
        await self.redis.ltrim(cache_key, -self.cache_size, -1)
        
        # Set expiration (1 hour)
        await self.redis.expire(cache_key, 3600)
        
        record_cache_op("set", "ok")
        
        logger.debug(
            "redis_cache_updated",
            ticket_id=ticket_id,
            cache_key=cache_key
        )
    
    async def get_thread(
        self,
        ticket_id: str,
        limit: Optional[int] = None
    ) -> List[Message]:
        """Retrieve conversation thread.
        
        Returns messages in chronological order. Attempts to retrieve from
        Redis cache first, falls back to PostgreSQL if cache miss or Redis unavailable.
        
        Args:
            ticket_id: Unique ticket identifier
            limit: Maximum number of messages to return (None for all)
        
        Returns:
            List of Message objects in chronological order
        """
        # Try Redis cache first for recent messages
        if limit and limit <= self.cache_size:
            try:
                cached_messages = await self._get_from_redis(ticket_id, limit)
                if cached_messages:
                    logger.debug(
                        "messages_retrieved_from_cache",
                        ticket_id=ticket_id,
                        count=len(cached_messages)
                    )
                    record_cache_op("get", "hit")
                    return cached_messages
                else:
                    record_cache_op("get", "miss")
            except Exception as e:
                logger.warning(
                    "redis_cache_read_failed",
                    ticket_id=ticket_id,
                    error=str(e),
                    message="Falling back to PostgreSQL"
                )
        
        # Fallback to PostgreSQL
        return await self._get_from_postgres(ticket_id, limit)
    
    async def _get_from_redis(
        self,
        ticket_id: str,
        limit: int
    ) -> Optional[List[Message]]:
        """Retrieve messages from Redis cache.
        
        Args:
            ticket_id: Unique ticket identifier
            limit: Maximum number of messages to return
        
        Returns:
            List of Message objects or None if cache miss
        """
        cache_key = f"conversation:{ticket_id}"
        
        # Get last N messages
        cached_data = await self.redis.lrange(cache_key, -limit, -1)
        
        if not cached_data:
            return None
        
        messages = []
        for data in cached_data:
            message_dict = json.loads(data)
            messages.append(Message(
                id=message_dict["id"],
                author=message_dict["author"],
                body=message_dict["body"],
                is_customer=message_dict["is_customer"],
                created_at=datetime.fromisoformat(message_dict["created_at"])
            ))
        
        return messages
    
    async def _get_from_postgres(
        self,
        ticket_id: str,
        limit: Optional[int]
    ) -> List[Message]:
        """Retrieve messages from PostgreSQL.
        
        Args:
            ticket_id: Unique ticket identifier
            limit: Maximum number of messages to return (None for all)
        
        Returns:
            List of Message objects in chronological order
        """
        try:
            async with self.postgres.acquire() as conn:
                if limit:
                    rows = await conn.fetch(
                        """
                        SELECT message_id, author, body, is_customer, created_at
                        FROM conversation_memory
                        WHERE ticket_id = $1
                        ORDER BY created_at ASC
                        LIMIT $2
                        """,
                        ticket_id,
                        limit
                    )
                else:
                    rows = await conn.fetch(
                        """
                        SELECT message_id, author, body, is_customer, created_at
                        FROM conversation_memory
                        WHERE ticket_id = $1
                        ORDER BY created_at ASC
                        """,
                        ticket_id
                    )
            
            messages = [
                Message(
                    id=row["message_id"],
                    author=row["author"],
                    body=row["body"],
                    is_customer=row["is_customer"],
                    created_at=row["created_at"]
                )
                for row in rows
            ]
            
            logger.info(
                "messages_retrieved_from_postgres",
                ticket_id=ticket_id,
                count=len(messages)
            )
            
            return messages
        
        except Exception as e:
            logger.error(
                "postgres_retrieval_failed",
                ticket_id=ticket_id,
                error=str(e)
            )
            raise DatabaseError(
                f"Failed to retrieve messages: {str(e)}",
                operation="get_thread"
            )
    
    async def get_recent_context(
        self,
        ticket_id: str,
        turns: int = 5
    ) -> str:
        """Get recent conversation as formatted context.
        
        Retrieves the last N conversation turns (customer + agent pairs)
        and formats them as a readable context string for LLM consumption.
        
        Args:
            ticket_id: Unique ticket identifier
            turns: Number of conversation turns to include (default: 5)
        
        Returns:
            Formatted conversation context string
        """
        # Get last N*2 messages (assuming turn = customer + agent)
        messages = await self.get_thread(ticket_id, limit=turns * 2)
        
        if not messages:
            return "No previous conversation history."
        
        # Format as context
        context_lines = ["Recent conversation history:"]
        for message in messages:
            role = "Customer" if message.is_customer else "Agent"
            timestamp = message.created_at.strftime("%Y-%m-%d %H:%M:%S")
            context_lines.append(f"\n[{timestamp}] {role} ({message.author}):")
            context_lines.append(message.body)
        
        context = "\n".join(context_lines)
        
        logger.debug(
            "context_generated",
            ticket_id=ticket_id,
            turns=turns,
            message_count=len(messages)
        )
        
        return context
    
    async def cleanup_old_conversations(self) -> int:
        """Delete conversations older than retention period.
        
        Implements automatic data retention policy by deleting
        conversations older than retention_days.
        
        Returns:
            Number of messages deleted
        """
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=self.retention_days)
            
            async with self.postgres.acquire() as conn:
                result = await conn.execute(
                    """
                    DELETE FROM conversation_memory
                    WHERE created_at < $1
                    """,
                    cutoff_date
                )
            
            # Extract count from result string "DELETE N"
            deleted_count = int(result.split()[-1]) if result else 0
            
            logger.info(
                "old_conversations_cleaned",
                deleted_count=deleted_count,
                cutoff_date=cutoff_date.isoformat(),
                retention_days=self.retention_days
            )
            
            return deleted_count
        
        except Exception as e:
            logger.error(
                "cleanup_failed",
                error=str(e)
            )
            raise DatabaseError(
                f"Failed to cleanup old conversations: {str(e)}",
                operation="cleanup_old_conversations"
            )
