# aise/knowledge_engine/extractor.py
"""Content extraction from HTML pages.

This module provides functionality to extract main content from HTML pages,
convert it to Markdown, and preserve heading structure for context.

Example usage:
    >>> from aise.knowledge_engine.extractor import ContentExtractor
    >>> 
    >>> extractor = ContentExtractor()
    >>> markdown = await extractor.extract_content(url, html)
    >>> print(markdown)
"""

from typing import Optional, Dict, Any
from bs4 import BeautifulSoup, Tag
import structlog
from markdownify import markdownify as md

from aise.core.exceptions import KnowledgeEngineError

logger = structlog.get_logger(__name__)


DEFAULT_UNWANTED_TAGS = [
    "script", "style", "noscript", "iframe", "embed", "object",
    "svg", "canvas", "audio", "video", "form", "input", "button",
    "select", "textarea",
]

DEFAULT_NAV_CLASSES = [
    "nav", "navigation", "menu", "sidebar", "footer",
    "header", "breadcrumb", "toc", "table-of-contents",
    "advertisement", "ad", "banner", "cookie", "popup",
]


class ContentExtractor:
    """Extracts and converts HTML content to Markdown."""

    def __init__(
        self,
        strip_tags: bool = True,
        convert_links: bool = True,
        preserve_images: bool = False,
        unwanted_tags: Optional[list] = None,
        nav_classes: Optional[list] = None,
    ):
        """Initialize content extractor.

        Args:
            strip_tags: Remove script, style, and other non-content tags
            convert_links: Convert HTML links to Markdown links
            preserve_images: Include images in Markdown output
            unwanted_tags: HTML tag names to strip entirely. Defaults to
                DEFAULT_UNWANTED_TAGS. Pass an empty list to strip nothing.
            nav_classes: CSS class substrings whose elements are removed as
                navigation/chrome. Defaults to DEFAULT_NAV_CLASSES.
        """
        self.strip_tags = strip_tags
        self.convert_links = convert_links
        self.preserve_images = preserve_images
        self.unwanted_tags = unwanted_tags if unwanted_tags is not None else DEFAULT_UNWANTED_TAGS
        self.nav_classes = nav_classes if nav_classes is not None else DEFAULT_NAV_CLASSES
    
    async def extract_content(
        self,
        url: str,
        html: str
    ) -> str:
        """Extract main content from HTML and convert to Markdown.
        
        Args:
            url: Source URL (for logging and context)
            html: HTML content to extract from
        
        Returns:
            Markdown content
        
        Raises:
            KnowledgeEngineError: If extraction fails
        """
        try:
            logger.debug("extracting_content", url=url)
            
            # Parse HTML
            soup = BeautifulSoup(html, "html.parser")
            
            # Remove unwanted elements
            if self.strip_tags:
                self._remove_unwanted_elements(soup)
            
            # Find main content
            main_content = self._find_main_content(soup)
            
            if not main_content:
                logger.warning("no_main_content_found", url=url)
                # Fall back to body
                main_content = soup.body if soup.body else soup
            
            # Convert to Markdown
            markdown = self._convert_to_markdown(main_content)
            
            # Clean up markdown
            markdown = self._clean_markdown(markdown)
            
            logger.debug(
                "content_extracted",
                url=url,
                length=len(markdown),
                lines=len(markdown.splitlines())
            )
            
            return markdown
            
        except Exception as e:
            logger.error("content_extraction_failed", url=url, error=str(e))
            raise KnowledgeEngineError(
                f"Failed to extract content from {url}: {str(e)}",
                field="url"
            )
    
    def _remove_unwanted_elements(self, soup: BeautifulSoup):
        """Remove script, style, and other unwanted elements.
        
        Args:
            soup: BeautifulSoup object to clean
        """
        for tag_name in self.unwanted_tags:
            for tag in soup.find_all(tag_name):
                tag.decompose()
        
        # Remove navigation, footer, header, sidebar semantic elements
        for tag in soup.find_all(["nav", "footer", "header", "aside"]):
            tag.decompose()
        
        for class_name in self.nav_classes:
            for tag in soup.find_all(class_=lambda x: x and class_name in x.lower()):
                tag.decompose()
        
        # Remove comments
        for comment in soup.find_all(string=lambda text: isinstance(text, str) and text.strip().startswith("<!--")):
            comment.extract()
    
    def _find_main_content(self, soup: BeautifulSoup) -> Optional[Tag]:
        """Find the main content area of the page.
        
        Args:
            soup: BeautifulSoup object
        
        Returns:
            Tag containing main content, or None if not found
        """
        # Try by ID first (AWS docs use id="main-content" or id="main-col-body")
        for id_name in ["main-content", "main-col-body", "main", "content", "article-body", "doc-content"]:
            element = soup.find(id=id_name)
            if element and len(element.get_text(strip=True)) > 100:
                return element

        # Try common main content selectors by tag/class
        selectors = [
            ("main", None),
            ("article", None),
            ("div", "main"),
            ("div", "content"),
            ("div", "article"),
            ("div", "documentation"),
            ("div", "docs"),
            ("div", "markdown-body"),
            ("section", "content"),
            ("section", "main"),
        ]
        
        for tag_name, class_name in selectors:
            if class_name:
                elements = soup.find_all(
                    tag_name,
                    class_=lambda x: x and class_name in x.lower()
                )
            else:
                elements = soup.find_all(tag_name)
            
            if elements:
                return elements[0]
        
        # Fall back to largest div with text
        divs = soup.find_all("div")
        if divs:
            divs_with_text = [
                (div, len(div.get_text(strip=True)))
                for div in divs
            ]
            divs_with_text.sort(key=lambda x: x[1], reverse=True)
            
            if divs_with_text and divs_with_text[0][1] > 100:
                return divs_with_text[0][0]
        
        return None
    
    def _convert_to_markdown(self, element: Tag) -> str:
        """Convert HTML element to Markdown.
        
        Args:
            element: BeautifulSoup Tag to convert
        
        Returns:
            Markdown string
        """
        # Convert to string
        html_str = str(element)
        
        # Convert to Markdown
        markdown = md(
            html_str,
            heading_style="ATX",
            bullets="-",
            strip=["script", "style", "nav", "footer", "header"] if not self.convert_links else ["script", "style", "nav", "footer", "header"],
            escape_asterisks=False,
            escape_underscores=False
        )
        
        return markdown
    
    def _clean_markdown(self, markdown: str) -> str:
        """Clean up markdown content.
        
        Args:
            markdown: Raw markdown string
        
        Returns:
            Cleaned markdown string
        """
        lines = markdown.splitlines()
        cleaned_lines = []
        
        prev_empty = False
        for line in lines:
            stripped = line.strip()
            
            # Skip empty lines (but keep one between sections)
            if not stripped:
                if not prev_empty:
                    cleaned_lines.append("")
                    prev_empty = True
                continue
            
            prev_empty = False
            
            # Skip lines that are just punctuation or special chars
            if all(c in "=-_*#[](){}|\\/" for c in stripped):
                continue
            
            cleaned_lines.append(line)
        
        # Join lines
        cleaned = "\n".join(cleaned_lines)
        
        # Remove excessive newlines (more than 2 consecutive)
        while "\n\n\n" in cleaned:
            cleaned = cleaned.replace("\n\n\n", "\n\n")
        
        # Strip leading/trailing whitespace
        cleaned = cleaned.strip()
        
        return cleaned
    
    def extract_metadata(self, html: str) -> Dict[str, Any]:
        """Extract metadata from HTML page.
        
        Args:
            html: HTML content
        
        Returns:
            Dictionary with metadata (title, description, etc.)
        """
        try:
            soup = BeautifulSoup(html, "html.parser")
            metadata = {}
            
            # Extract title
            title_tag = soup.find("title")
            if title_tag:
                metadata["title"] = title_tag.get_text(strip=True)
            
            # Extract meta description
            meta_desc = soup.find("meta", attrs={"name": "description"})
            if meta_desc and meta_desc.get("content"):
                metadata["description"] = meta_desc["content"]
            
            # Extract meta keywords
            meta_keywords = soup.find("meta", attrs={"name": "keywords"})
            if meta_keywords and meta_keywords.get("content"):
                metadata["keywords"] = meta_keywords["content"]
            
            # Extract Open Graph metadata
            og_title = soup.find("meta", property="og:title")
            if og_title and og_title.get("content"):
                metadata["og_title"] = og_title["content"]
            
            og_desc = soup.find("meta", property="og:description")
            if og_desc and og_desc.get("content"):
                metadata["og_description"] = og_desc["content"]
            
            # Extract canonical URL
            canonical = soup.find("link", rel="canonical")
            if canonical and canonical.get("href"):
                metadata["canonical_url"] = canonical["href"]
            
            # Extract language
            html_tag = soup.find("html")
            if html_tag and html_tag.get("lang"):
                metadata["language"] = html_tag["lang"]
            
            return metadata
            
        except Exception as e:
            logger.warning("metadata_extraction_failed", error=str(e))
            return {}
