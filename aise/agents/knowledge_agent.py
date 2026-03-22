# aise/agents/knowledge_agent.py
"""Documentation retrieval agent.

This module provides the Knowledge Agent responsible for retrieving
relevant documentation from the vector store to provide context for
AI responses.

Example usage:
    >>> from aise.agents.knowledge_agent import KnowledgeAgent
    >>> from aise.knowledge_engine.vector_store import ChromaDBVectorStore
    >>> from aise.knowledge_engine.embedder import OpenAIEmbedder
    >>> from aise.core.config import get_config
    >>> 
    >>> config = get_config()
    >>> vector_store = ChromaDBVectorStore(config)
    >>> await vector_store.initialize()
    >>> 
    >>> embedder = OpenAIEmbedder(api_key=config.OPENAI_API_KEY)
    >>> agent = KnowledgeAgent(vector_store, embedder)
    >>> results = await agent.retrieve("How do I configure security groups?", top_k=5)
"""

import structlog
from typing import List, Dict, Optional
from aise.observability.tracer import get_tracer, agent_span

logger = structlog.get_logger(__name__)


class KnowledgeAgent:
    """Agent responsible for retrieving relevant documentation.
    
    The Knowledge Agent searches the vector store for documentation
    chunks relevant to user queries and returns them with source
    citations for context injection into AI responses.
    """
    
    def __init__(self, vector_store, embedder):
        """Initialize knowledge agent.
        
        Args:
            vector_store: Vector store instance for documentation retrieval
            embedder: Embedder instance for query embedding generation
        """
        self._vector_store = vector_store
        self._embedder = embedder
        self._tracer = get_tracer("aise.agents.knowledge")
    
    async def retrieve(
        self,
        query: str,
        top_k: int = 5,
        source_filter: Optional[str] = None
    ) -> List[Dict]:
        """Retrieve relevant documentation chunks.
        
        Searches the vector store for documentation relevant to the query.
        Returns empty list if the index is empty (not yet initialized).
        
        Args:
            query: User query or question
            top_k: Number of top results to return
            source_filter: Optional source name to filter results (e.g., "aws")
        
        Returns:
            List of dictionaries containing:
                - text: Chunk text content
                - source_url: Original documentation URL
                - source_name: Documentation source name
                - heading_context: Parent headings for context
                - score: Relevance score (distance from query)
        """
        try:
            # Check if index is empty before attempting retrieval
            indexed_sources = await self._vector_store.list_all_sources()
            
            if not indexed_sources:
                logger.warning(
                    "knowledge_index_empty",
                    message="No documentation indexed yet. Run 'aise init' to index documentation."
                )
                return []
            
            with agent_span(
                self._tracer,
                "knowledge_agent.retrieve",
                {
                    "agent.query_length": len(query),
                    "agent.top_k": top_k,
                    "agent.source_filter": source_filter or "",
                    "agent.indexed_sources": len(indexed_sources),
                },
            ) as span:
                logger.info(
                    "knowledge_retrieval_started",
                    query=query[:100],
                    top_k=top_k,
                    source_filter=source_filter,
                    indexed_sources=len(indexed_sources)
                )
                
                # Build filter for vector store search
                filter_dict = None
                if source_filter:
                    filter_dict = {"source": source_filter}
                
                # Search vector store (ChromaDB handles embedding internally)
                chunks = await self._vector_store.search(
                    query=query,
                    top_k=top_k,
                    filter=filter_dict
                )
                
                # Convert DocumentChunk objects to result dictionaries
                # ChromaDB returns results ordered by ascending distance (lower = more similar).
                # We convert distance → similarity score: score = 1 / (1 + distance)
                results = []
                for chunk in chunks:
                    # ChromaDB stores the distance in chunk metadata when available
                    raw_distance = chunk.metadata.get("_distance")
                    if raw_distance is not None:
                        score = 1.0 / (1.0 + float(raw_distance))
                    else:
                        # Fallback: no distance info, treat as high relevance
                        score = 1.0
                    result = {
                        "text": chunk.content,
                        "source_url": chunk.source_url,
                        "source_name": chunk.metadata.get("source", "unknown"),
                        "heading_context": chunk.heading_context,
                        "score": score,
                    }
                    results.append(result)
                
                span.set_attribute("agent.results_count", len(results))
                
                logger.info(
                    "knowledge_retrieval_completed",
                    query=query[:100],
                    results_count=len(results),
                    source_filter=source_filter
                )
                
                return results
            
        except Exception as e:
            logger.error(
                "knowledge_retrieval_failed",
                query=query[:100],
                error=str(e)
            )
            # Return empty list on error to allow graceful degradation
            return []
