# aise/knowledge_engine/vector_store.py
"""Vector store abstraction and ChromaDB implementation.

This module provides an abstract interface for vector stores and a concrete
implementation using ChromaDB for persistent storage of document embeddings.

Example usage:
    >>> from aise.knowledge_engine.vector_store import ChromaDBVectorStore
    >>> from aise.core.config import get_config
    >>> 
    >>> config = get_config()
    >>> store = ChromaDBVectorStore(config)
    >>> await store.initialize()
    >>> 
    >>> # Upsert document chunks
    >>> chunks = [
    ...     DocumentChunk(
    ...         id="doc1_chunk1",
    ...         content="AWS EC2 is a compute service...",
    ...         metadata={"source": "aws", "section": "EC2"},
    ...         source_url="https://docs.aws.amazon.com/ec2/",
    ...         heading_context="EC2 > Getting Started",
    ...         embedding=[0.1, 0.2, ...]
    ...     )
    ... ]
    >>> await store.upsert(chunks)
    >>> 
    >>> # Search for relevant chunks
    >>> results = await store.search("How do I launch an EC2 instance?", top_k=5)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict, Any
from datetime import datetime
import hashlib
import structlog
from aise.observability.metrics import VECTOR_STORE_QUERY_LATENCY

try:
    import chromadb
    from chromadb.config import Settings
    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False

from aise.core.exceptions import KnowledgeEngineError

logger = structlog.get_logger(__name__)


@dataclass
class DocumentChunk:
    """Represents a chunk of documentation with embeddings.
    
    Attributes:
        id: Unique identifier (hash of content + source_url)
        content: Markdown text content
        metadata: Additional metadata (source, section, etc.)
        source_url: Original documentation URL
        heading_context: Parent headings for context
        embedding: Vector embedding (optional, generated if not provided)
        created_at: Creation timestamp
    """
    id: str
    content: str
    metadata: Dict[str, Any]
    source_url: str
    heading_context: str
    embedding: Optional[List[float]] = None
    created_at: str = None
    
    def __post_init__(self):
        """Set default values after initialization."""
        if self.created_at is None:
            self.created_at = datetime.utcnow().isoformat()
        
        # Generate deterministic ID if not provided
        if not self.id:
            self.id = self.generate_id(self.content, self.source_url)
    
    @staticmethod
    def generate_id(content: str, source_url: str, index: int = 0) -> str:
        """Generate deterministic chunk ID from content, URL, and position index.
        
        Including the index prevents two chunks with identical content at
        different positions in the same document from colliding.
        
        Args:
            content: Chunk content
            source_url: Source URL
            index: Position index within the document (default 0)
        
        Returns:
            SHA256 hash as hex string
        """
        combined = f"{source_url}:{index}:{content}"
        return hashlib.sha256(combined.encode()).hexdigest()


class VectorStore(ABC):
    """Abstract base class for vector stores.
    
    Provides interface for storing and retrieving document embeddings.
    """
    
    @abstractmethod
    async def initialize(self) -> None:
        """Initialize vector store connection and collections."""
        pass
    
    @abstractmethod
    async def upsert(self, chunks: List[DocumentChunk]) -> None:
        """Insert or update document chunks.
        
        Args:
            chunks: List of DocumentChunk objects to upsert
        """
        pass
    
    @abstractmethod
    async def search(
        self,
        query: str,
        top_k: int = 5,
        filter: Optional[Dict[str, Any]] = None
    ) -> List[DocumentChunk]:
        """Search for relevant document chunks.
        
        Args:
            query: Search query text
            top_k: Number of results to return
            filter: Optional metadata filter
        
        Returns:
            List of relevant DocumentChunk objects
        """
        pass
    
    @abstractmethod
    async def delete(self, chunk_ids: List[str]) -> None:
        """Delete document chunks by ID.
        
        Args:
            chunk_ids: List of chunk IDs to delete
        """
        pass
    
    @abstractmethod
    async def get_collection_stats(self) -> Dict[str, Any]:
        """Get statistics about the vector store.
        
        Returns:
            Dictionary with collection statistics
        """
        pass
    
    @abstractmethod
    async def close(self) -> None:
        """Close vector store connection."""
        pass


class ChromaDBVectorStore(VectorStore):
    """ChromaDB implementation of vector store.
    
    Uses ChromaDB for persistent storage of document embeddings with
    support for metadata filtering and similarity search.
    
    Attributes:
        _config: Configuration instance
        _client: ChromaDB client
        _collection: ChromaDB collection for documents
        _user_style_collection: ChromaDB collection for user style
    
    Example:
        >>> store = ChromaDBVectorStore(config)
        >>> await store.initialize()
        >>> await store.upsert(chunks)
        >>> results = await store.search("query", top_k=5)
    """
    
    def __init__(self, config):
        """Initialize ChromaDB vector store.
        
        Args:
            config: Configuration instance with ChromaDB settings
        
        Raises:
            KnowledgeEngineError: If ChromaDB is not installed
        """
        if not CHROMADB_AVAILABLE:
            raise KnowledgeEngineError(
                "ChromaDB is not installed. Install with: pip install chromadb",
                operation="initialization"
            )
        
        self._config = config
        self._client = None
        self._collection = None
        self._user_style_collection = None
    
    async def initialize(self) -> None:
        """Initialize ChromaDB client and collections.
        
        Creates persistent client and document/user_style collections.
        """
        try:
            # Create persistent client
            chroma_host = getattr(self._config, 'CHROMA_HOST', 'localhost')
            chroma_port = getattr(self._config, 'CHROMA_PORT', 8000)
            
            self._client = chromadb.HttpClient(
                host=chroma_host,
                port=chroma_port,
                settings=Settings(
                    anonymized_telemetry=False,
                    allow_reset=False
                )
            )
            
            # Create or get document collection
            self._collection = self._client.get_or_create_collection(
                name="aise_documents",
                metadata={"description": "AiSE documentation chunks"}
            )
            
            # Create or get user style collection
            self._user_style_collection = self._client.get_or_create_collection(
                name="aise_user_style",
                metadata={"description": "AiSE user communication style examples"}
            )
            
            logger.info(
                "chromadb_initialized",
                host=chroma_host,
                port=chroma_port,
                document_count=self._collection.count(),
                user_style_count=self._user_style_collection.count()
            )
            
        except Exception as e:
            logger.error(
                "chromadb_initialization_failed",
                error=str(e)
            )
            raise KnowledgeEngineError(
                f"Failed to initialize ChromaDB: {str(e)}",
                operation="initialization"
            )

    
    async def upsert(self, chunks: List[DocumentChunk]) -> None:
        """Insert or update document chunks in ChromaDB.
        
        Args:
            chunks: List of DocumentChunk objects to upsert
        
        Raises:
            KnowledgeEngineError: If upsert fails
        """
        if not self._collection:
            raise KnowledgeEngineError(
                "Vector store not initialized",
                operation="upsert"
            )
        
        if not chunks:
            return
        
        try:
            # Deduplicate chunks by ID within this batch (last one wins)
            seen = {}
            for chunk in chunks:
                seen[chunk.id] = chunk
            chunks = list(seen.values())

            # Prepare data for ChromaDB
            ids = [chunk.id for chunk in chunks]
            documents = [chunk.content for chunk in chunks]
            metadatas = [
                {
                    **chunk.metadata,
                    "source_url": chunk.source_url,
                    "heading_context": chunk.heading_context,
                    "created_at": chunk.created_at
                }
                for chunk in chunks
            ]
            
            # Add embeddings if provided
            embeddings = None
            if chunks[0].embedding is not None:
                embeddings = [chunk.embedding for chunk in chunks]
            
            # Upsert to ChromaDB
            if embeddings:
                self._collection.upsert(
                    ids=ids,
                    documents=documents,
                    metadatas=metadatas,
                    embeddings=embeddings
                )
            else:
                # ChromaDB will generate embeddings
                self._collection.upsert(
                    ids=ids,
                    documents=documents,
                    metadatas=metadatas
                )
            
            logger.info(
                "chunks_upserted",
                count=len(chunks),
                collection="aise_documents"
            )
            
        except Exception as e:
            logger.error(
                "chunk_upsert_failed",
                error=str(e),
                chunk_count=len(chunks)
            )
            raise KnowledgeEngineError(
                f"Failed to upsert chunks: {str(e)}",
                operation="upsert"
            )
    
    async def search(
        self,
        query: str,
        top_k: int = 5,
        filter: Optional[Dict[str, Any]] = None
    ) -> List[DocumentChunk]:
        """Search for relevant document chunks using similarity search.
        
        Args:
            query: Search query text
            top_k: Number of results to return
            filter: Optional metadata filter (e.g., {"source": "aws"})
        
        Returns:
            List of relevant DocumentChunk objects
        
        Raises:
            KnowledgeEngineError: If search fails
        """
        if not self._collection:
            raise KnowledgeEngineError(
                "Vector store not initialized",
                operation="search"
            )
        
        try:
            import time as _time
            _t0 = _time.monotonic()
            # Query ChromaDB
            results = self._collection.query(
                query_texts=[query],
                n_results=top_k,
                where=filter
            )
            VECTOR_STORE_QUERY_LATENCY.observe(_time.monotonic() - _t0)
            
            # Convert results to DocumentChunk objects
            chunks = []
            if results['ids'] and results['ids'][0]:
                distances = results.get('distances', [[]])[0]
                for i in range(len(results['ids'][0])):
                    metadata = results['metadatas'][0][i]
                    
                    # Carry the raw distance so callers can compute real similarity scores
                    extra_meta = {}
                    if i < len(distances):
                        extra_meta["_distance"] = distances[i]
                    
                    chunk = DocumentChunk(
                        id=results['ids'][0][i],
                        content=results['documents'][0][i],
                        metadata={
                            **{k: v for k, v in metadata.items()
                               if k not in ['source_url', 'heading_context', 'created_at']},
                            **extra_meta,
                        },
                        source_url=metadata.get('source_url', ''),
                        heading_context=metadata.get('heading_context', ''),
                        embedding=results['embeddings'][0][i] if results.get('embeddings') else None,
                        created_at=metadata.get('created_at')
                    )
                    chunks.append(chunk)
            
            logger.info(
                "search_completed",
                query=query[:50],
                results_count=len(chunks),
                filter=filter
            )
            
            return chunks
            
        except Exception as e:
            logger.error(
                "search_failed",
                error=str(e),
                query=query[:50]
            )
            raise KnowledgeEngineError(
                f"Failed to search chunks: {str(e)}",
                operation="search"
            )
    
    async def delete(self, chunk_ids: List[str]) -> None:
        """Delete document chunks by ID.
        
        Args:
            chunk_ids: List of chunk IDs to delete
        
        Raises:
            KnowledgeEngineError: If deletion fails
        """
        if not self._collection:
            raise KnowledgeEngineError(
                "Vector store not initialized",
                operation="delete"
            )
        
        if not chunk_ids:
            return
        
        try:
            self._collection.delete(ids=chunk_ids)
            
            logger.info(
                "chunks_deleted",
                count=len(chunk_ids)
            )
            
        except Exception as e:
            logger.error(
                "chunk_deletion_failed",
                error=str(e),
                chunk_count=len(chunk_ids)
            )
            raise KnowledgeEngineError(
                f"Failed to delete chunks: {str(e)}",
                operation="delete"
            )
    
    async def get_collection_stats(self) -> Dict[str, Any]:
        """Get statistics about the vector store collections.
        
        Returns:
            Dictionary with collection statistics
        """
        if not self._collection:
            return {
                "initialized": False
            }
        
        try:
            return {
                "initialized": True,
                "document_count": self._collection.count(),
                "user_style_count": self._user_style_collection.count() if self._user_style_collection else 0,
                "collections": ["aise_documents", "aise_user_style"]
            }
        except Exception as e:
            logger.error(
                "stats_retrieval_failed",
                error=str(e)
            )
            return {
                "initialized": True,
                "error": str(e)
            }
    
    async def record_source_crawl(
        self,
        source_name: str,
        url: str,
        chunk_count: int,
        embedding_model: str
    ) -> None:
        """Store crawl timestamp and stats for a source.
        
        Args:
            source_name: Name of the documentation source
            url: Source URL
            chunk_count: Number of chunks indexed
            embedding_model: Embedding model used
        
        Raises:
            KnowledgeEngineError: If recording fails
        """
        if not self._client:
            raise KnowledgeEngineError(
                "Vector store not initialized",
                operation="record_source_crawl"
            )
        
        try:
            # Get or create source_metadata collection
            metadata_collection = self._client.get_or_create_collection(
                name="aise_source_metadata",
                metadata={"description": "AiSE source crawl metadata"}
            )
            
            # Store metadata
            crawled_at = datetime.utcnow().isoformat()
            metadata_collection.upsert(
                ids=[source_name],
                documents=[f"Source: {source_name}"],
                metadatas=[{
                    "source_name": source_name,
                    "url": url,
                    "chunk_count": chunk_count,
                    "embedding_model": embedding_model,
                    "crawled_at": crawled_at
                }]
            )
            
            logger.info(
                "source_crawl_recorded",
                source_name=source_name,
                chunk_count=chunk_count,
                crawled_at=crawled_at
            )
            
        except Exception as e:
            logger.error(
                "record_source_crawl_failed",
                error=str(e),
                source_name=source_name
            )
            raise KnowledgeEngineError(
                f"Failed to record source crawl: {str(e)}",
                operation="record_source_crawl"
            )
    
    async def get_source_status(self, source_name: str) -> Optional[Dict[str, Any]]:
        """Return crawl metadata for a source, or None if never crawled.
        
        Args:
            source_name: Name of the documentation source
        
        Returns:
            Dictionary with crawl metadata or None if not found
        """
        if not self._client:
            return None
        
        try:
            # Get source_metadata collection
            metadata_collection = self._client.get_or_create_collection(
                name="aise_source_metadata",
                metadata={"description": "AiSE source crawl metadata"}
            )
            
            # Query for source
            results = metadata_collection.get(
                ids=[source_name]
            )
            
            if results['ids']:
                metadata = results['metadatas'][0]
                return {
                    "source_name": metadata.get("source_name"),
                    "url": metadata.get("url"),
                    "chunk_count": metadata.get("chunk_count"),
                    "embedding_model": metadata.get("embedding_model"),
                    "crawled_at": metadata.get("crawled_at")
                }
            
            return None
            
        except Exception as e:
            logger.error(
                "get_source_status_failed",
                error=str(e),
                source_name=source_name
            )
            return None
    
    async def list_all_sources(self) -> List[Dict[str, Any]]:
        """Return all tracked sources with their crawl metadata.
        
        Returns:
            List of source metadata dictionaries
        """
        if not self._client:
            return []
        
        try:
            # Get source_metadata collection
            metadata_collection = self._client.get_or_create_collection(
                name="aise_source_metadata",
                metadata={"description": "AiSE source crawl metadata"}
            )
            
            # Get all sources
            results = metadata_collection.get()
            
            sources = []
            if results['ids']:
                for i in range(len(results['ids'])):
                    metadata = results['metadatas'][i]
                    sources.append({
                        "source_name": metadata.get("source_name"),
                        "url": metadata.get("url"),
                        "chunk_count": metadata.get("chunk_count"),
                        "embedding_model": metadata.get("embedding_model"),
                        "crawled_at": metadata.get("crawled_at")
                    })
            
            return sources
            
        except Exception as e:
            logger.error(
                "list_all_sources_failed",
                error=str(e)
            )
            return []
    
    async def delete_source(self, source_name: str) -> int:
        """Delete all chunks and metadata for a source.
        
        Args:
            source_name: Name of the documentation source
        
        Returns:
            Number of chunks deleted
        
        Raises:
            KnowledgeEngineError: If deletion fails
        """
        if not self._collection or not self._client:
            raise KnowledgeEngineError(
                "Vector store not initialized",
                operation="delete_source"
            )
        
        try:
            # Get all chunks for this source
            results = self._collection.get(
                where={"source": source_name}
            )
            
            chunk_count = len(results['ids']) if results['ids'] else 0
            
            # Delete chunks
            if chunk_count > 0:
                self._collection.delete(
                    where={"source": source_name}
                )
            
            # Delete metadata
            metadata_collection = self._client.get_or_create_collection(
                name="aise_source_metadata",
                metadata={"description": "AiSE source crawl metadata"}
            )
            
            try:
                metadata_collection.delete(ids=[source_name])
            except:
                pass  # Metadata might not exist
            
            logger.info(
                "source_deleted",
                source_name=source_name,
                chunks_deleted=chunk_count
            )
            
            return chunk_count
            
        except Exception as e:
            logger.error(
                "delete_source_failed",
                error=str(e),
                source_name=source_name
            )
            raise KnowledgeEngineError(
                f"Failed to delete source: {str(e)}",
                operation="delete_source"
            )
    
    async def close(self) -> None:
        """Close ChromaDB connection.
        
        ChromaDB HTTP client doesn't require explicit closing,
        but this method is provided for interface compatibility.
        """
        logger.info("chromadb_connection_closed")
        self._client = None
        self._collection = None
        self._user_style_collection = None
    
    async def upsert_user_style(self, interactions: List[Dict[str, Any]]) -> None:
        """Upsert user style interactions to separate collection.
        
        Args:
            interactions: List of user interaction dictionaries
        
        Raises:
            KnowledgeEngineError: If upsert fails
        """
        if not self._user_style_collection:
            raise KnowledgeEngineError(
                "User style collection not initialized",
                operation="upsert_user_style"
            )
        
        if not interactions:
            return
        
        try:
            ids = [interaction['id'] for interaction in interactions]
            documents = [interaction['message'] for interaction in interactions]
            metadatas = [
                {
                    "timestamp": interaction.get('timestamp'),
                    "context": interaction.get('context', 'unknown'),
                    "tone_indicators": ','.join(interaction.get('tone_indicators', []))
                }
                for interaction in interactions
            ]
            
            self._user_style_collection.upsert(
                ids=ids,
                documents=documents,
                metadatas=metadatas
            )
            
            logger.info(
                "user_style_upserted",
                count=len(interactions)
            )
            
        except Exception as e:
            logger.error(
                "user_style_upsert_failed",
                error=str(e)
            )
            raise KnowledgeEngineError(
                f"Failed to upsert user style: {str(e)}",
                operation="upsert_user_style"
            )
    
    async def search_user_style(
        self,
        query: str,
        top_k: int = 5
    ) -> List[Dict[str, Any]]:
        """Search for similar user style examples.
        
        Args:
            query: Search query text
            top_k: Number of results to return
        
        Returns:
            List of user style interaction dictionaries
        
        Raises:
            KnowledgeEngineError: If search fails
        """
        if not self._user_style_collection:
            raise KnowledgeEngineError(
                "User style collection not initialized",
                operation="search_user_style"
            )
        
        try:
            results = self._user_style_collection.query(
                query_texts=[query],
                n_results=top_k
            )
            
            interactions = []
            if results['ids'] and results['ids'][0]:
                for i in range(len(results['ids'][0])):
                    metadata = results['metadatas'][0][i]
                    
                    interaction = {
                        'id': results['ids'][0][i],
                        'message': results['documents'][0][i],
                        'timestamp': metadata.get('timestamp'),
                        'context': metadata.get('context'),
                        'tone_indicators': metadata.get('tone_indicators', '').split(',') if metadata.get('tone_indicators') else []
                    }
                    interactions.append(interaction)
            
            logger.info(
                "user_style_search_completed",
                results_count=len(interactions)
            )
            
            return interactions
            
        except Exception as e:
            logger.error(
                "user_style_search_failed",
                error=str(e)
            )
            raise KnowledgeEngineError(
                f"Failed to search user style: {str(e)}",
                operation="search_user_style"
            )
