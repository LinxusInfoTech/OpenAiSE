# aise/knowledge_engine/chunker.py
"""Text chunking for documentation with context preservation.

This module provides semantic text chunking that splits documents into
manageable chunks while preserving heading context and maintaining
semantic coherence.

Example usage:
    >>> from aise.knowledge_engine.chunker import TextChunker
    >>> 
    >>> chunker = TextChunker(chunk_size=1000, chunk_overlap=150)
    >>> chunks = chunker.chunk(markdown_text, source_url="https://docs.example.com")
    >>> print(f"Created {len(chunks)} chunks")
"""

import hashlib
from typing import List, Optional
from dataclasses import dataclass
import structlog

from aise.core.exceptions import KnowledgeEngineError

logger = structlog.get_logger(__name__)


@dataclass
class DocumentChunk:
    """Represents a chunk of documentation."""
    id: str
    content: str
    metadata: dict
    source_url: str
    heading_context: str
    embedding: Optional[List[float]] = None
    created_at: Optional[str] = None


class TextChunker:
    """Splits documents into semantic chunks with context preservation."""
    
    def __init__(
        self,
        chunk_size: int = 1000,
        chunk_overlap: int = 150,
        min_chunk_size: int = 100
    ):
        """Initialize text chunker.
        
        Args:
            chunk_size: Target size for each chunk in characters
            chunk_overlap: Number of characters to overlap between chunks
            min_chunk_size: Minimum chunk size (smaller chunks are merged)
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.min_chunk_size = min_chunk_size
        
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be less than chunk_size")
        
        if min_chunk_size > chunk_size:
            raise ValueError("min_chunk_size must be less than or equal to chunk_size")
    
    def chunk(
        self,
        text: str,
        source_url: str,
        metadata: Optional[dict] = None
    ) -> List[DocumentChunk]:
        """Split text into overlapping chunks with context preservation.
        
        Args:
            text: Markdown text to chunk
            source_url: Source URL for the document
            metadata: Additional metadata for chunks
        
        Returns:
            List of DocumentChunk objects
        
        Raises:
            KnowledgeEngineError: If chunking fails
        """
        try:
            if not text or not text.strip():
                logger.warning("empty_text_for_chunking", source_url=source_url)
                return []
            
            logger.debug(
                "chunking_text",
                source_url=source_url,
                text_length=len(text),
                chunk_size=self.chunk_size
            )
            
            # Parse document structure
            sections = self._parse_sections(text)
            
            # Create chunks from sections
            chunks = []
            for section in sections:
                section_chunks = self._chunk_section(
                    section["content"],
                    section["heading_context"],
                    source_url,
                    metadata or {}
                )
                chunks.extend(section_chunks)
            
            # Re-assign IDs with global index to guarantee uniqueness
            seen_ids = {}
            for i, chunk in enumerate(chunks):
                base_id = self._generate_chunk_id(chunk.content, source_url, i)
                # Extra safety: if still colliding, append counter
                if base_id in seen_ids:
                    seen_ids[base_id] += 1
                    chunk.id = f"{base_id}{seen_ids[base_id]:02x}"
                else:
                    seen_ids[base_id] = 0
                    chunk.id = base_id
            
            logger.info(
                "chunking_complete",
                source_url=source_url,
                total_chunks=len(chunks),
                avg_chunk_size=sum(len(c.content) for c in chunks) // len(chunks) if chunks else 0
            )
            
            return chunks
            
        except Exception as e:
            logger.error("chunking_failed", source_url=source_url, error=str(e))
            raise KnowledgeEngineError(
                f"Failed to chunk text from {source_url}: {str(e)}",
                field="text"
            )
    
    def _parse_sections(self, text: str) -> List[dict]:
        """Parse markdown text into sections with heading context.
        
        Args:
            text: Markdown text
        
        Returns:
            List of sections with heading context
        """
        lines = text.splitlines()
        sections = []
        
        current_section = {
            "heading_context": "",
            "content": "",
            "level": 0
        }
        
        heading_stack = []  # Stack of (level, heading) tuples
        
        for line in lines:
            # Check if line is a heading
            if line.startswith("#"):
                # Count heading level
                level = 0
                for char in line:
                    if char == "#":
                        level += 1
                    else:
                        break
                
                heading_text = line[level:].strip()
                
                # Save current section if it has content
                if current_section["content"].strip():
                    sections.append(current_section.copy())
                
                # Update heading stack
                # Remove headings at same or deeper level
                heading_stack = [
                    (l, h) for l, h in heading_stack if l < level
                ]
                
                # Add new heading
                heading_stack.append((level, heading_text))
                
                # Build heading context
                heading_context = " > ".join(h for _, h in heading_stack)
                
                # Start new section
                current_section = {
                    "heading_context": heading_context,
                    "content": line + "\n",
                    "level": level
                }
            else:
                # Add line to current section
                current_section["content"] += line + "\n"
        
        # Add final section
        if current_section["content"].strip():
            sections.append(current_section)
        
        return sections
    
    def _chunk_section(
        self,
        content: str,
        heading_context: str,
        source_url: str,
        metadata: dict
    ) -> List[DocumentChunk]:
        """Chunk a single section.
        
        Args:
            content: Section content
            heading_context: Heading context for the section
            source_url: Source URL
            metadata: Metadata dictionary
        
        Returns:
            List of DocumentChunk objects
        """
        chunks = []
        
        # If section is small enough, create single chunk
        if len(content) <= self.chunk_size:
            chunk = self._create_chunk(
                content,
                heading_context,
                source_url,
                metadata
            )
            chunks.append(chunk)
            return chunks
        
        # Split into sentences for better semantic boundaries
        sentences = self._split_into_sentences(content)
        
        # Build chunks from sentences
        current_chunk = ""
        current_sentences = []
        
        for sentence in sentences:
            # Check if adding this sentence would exceed chunk size
            if len(current_chunk) + len(sentence) > self.chunk_size and current_chunk:
                # Create chunk from accumulated sentences
                chunk = self._create_chunk(
                    current_chunk,
                    heading_context,
                    source_url,
                    metadata
                )
                chunks.append(chunk)
                
                # Start new chunk with overlap
                overlap_text = self._get_overlap_text(current_sentences)
                current_chunk = overlap_text
                current_sentences = [s for s in current_sentences if s in overlap_text]
            
            # Add sentence to current chunk
            current_chunk += sentence
            current_sentences.append(sentence)
        
        # Add final chunk
        if current_chunk.strip() and len(current_chunk.strip()) >= self.min_chunk_size:
            chunk = self._create_chunk(
                current_chunk,
                heading_context,
                source_url,
                metadata
            )
            chunks.append(chunk)
        elif chunks and current_chunk.strip():
            # Merge small final chunk with previous chunk
            chunks[-1].content += "\n" + current_chunk
            chunks[-1].id = self._generate_chunk_id(chunks[-1].content, source_url, len(chunks) - 1)
        
        return chunks
    
    def _split_into_sentences(self, text: str) -> List[str]:
        """Split text into sentences.
        
        Args:
            text: Text to split
        
        Returns:
            List of sentences
        """
        # Simple sentence splitting (can be improved with NLP)
        sentences = []
        current = ""
        
        for char in text:
            current += char
            
            # Check for sentence boundaries
            if char in ".!?" and len(current) > 10:
                # Look ahead to see if this is really end of sentence
                sentences.append(current)
                current = ""
        
        # Add remaining text
        if current.strip():
            sentences.append(current)
        
        return sentences
    
    def _get_overlap_text(self, sentences: List[str]) -> str:
        """Get overlap text from end of sentences.
        
        Args:
            sentences: List of sentences
        
        Returns:
            Overlap text
        """
        overlap = ""
        for sentence in reversed(sentences):
            if len(overlap) + len(sentence) <= self.chunk_overlap:
                overlap = sentence + overlap
            else:
                break
        
        return overlap
    
    def _create_chunk(
        self,
        content: str,
        heading_context: str,
        source_url: str,
        metadata: dict
    ) -> DocumentChunk:
        """Create a DocumentChunk object.
        
        Args:
            content: Chunk content
            heading_context: Heading context
            source_url: Source URL
            metadata: Metadata dictionary
        
        Returns:
            DocumentChunk object
        """
        # Generate deterministic ID
        chunk_id = self._generate_chunk_id(content, source_url)
        
        # Create metadata
        chunk_metadata = {
            **metadata,
            "chunk_size": len(content),
            "heading_context": heading_context
        }
        
        return DocumentChunk(
            id=chunk_id,
            content=content.strip(),
            metadata=chunk_metadata,
            source_url=source_url,
            heading_context=heading_context,
            embedding=None,
            created_at=None
        )
    
    def _generate_chunk_id(self, content: str, source_url: str, index: int = 0) -> str:
        """Generate deterministic chunk ID.
        
        Args:
            content: Chunk content
            source_url: Source URL
            index: Position index to ensure uniqueness for identical content
        
        Returns:
            Chunk ID (hash)
        """
        # Include index to prevent collisions from identical content across pages
        hash_input = f"{source_url}:{index}:{content}".encode("utf-8")
        return hashlib.sha256(hash_input).hexdigest()[:16]
