# aise/knowledge_engine/crawler.py
"""Async web crawler for documentation learning.

This module provides an async web crawler that respects robots.txt,
implements rate limiting, and supports configurable crawl depth and page limits.

Example usage:
    >>> from aise.knowledge_engine.crawler import DocumentCrawler
    >>> 
    >>> crawler = DocumentCrawler(max_depth=3, max_pages=100)
    >>> urls = await crawler.crawl("https://docs.example.com")
    >>> print(f"Crawled {len(urls)} pages")
"""

import asyncio
import aiohttp
from typing import List, Set, Optional, Dict
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser
import structlog
from datetime import datetime, timedelta
from collections import defaultdict

from aise.core.exceptions import KnowledgeEngineError

logger = structlog.get_logger(__name__)


class RateLimiter:
    """Rate limiter for web requests."""
    
    def __init__(self, requests_per_second: float = 2.0):
        """Initialize rate limiter.
        
        Args:
            requests_per_second: Maximum requests per second per domain
        """
        self.requests_per_second = requests_per_second
        self.min_interval = 1.0 / requests_per_second
        self.last_request_time: Dict[str, datetime] = defaultdict(lambda: datetime.min)
        self._lock = asyncio.Lock()
    
    async def acquire(self, domain: str):
        """Acquire permission to make a request to a domain.
        
        Args:
            domain: Domain name to rate limit
        """
        async with self._lock:
            now = datetime.now()
            last_request = self.last_request_time[domain]
            time_since_last = (now - last_request).total_seconds()
            
            if time_since_last < self.min_interval:
                wait_time = self.min_interval - time_since_last
                logger.debug(
                    "rate_limit_wait",
                    domain=domain,
                    wait_time=wait_time
                )
                await asyncio.sleep(wait_time)
            
            self.last_request_time[domain] = datetime.now()


class DocumentCrawler:
    """Async web crawler for documentation websites."""
    
    def __init__(
        self,
        max_depth: int = 3,
        max_pages: int = 1000,
        requests_per_second: float = 2.0,
        timeout: int = 30,
        user_agent: str = "AiSE-DocumentCrawler/1.0"
    ):
        """Initialize document crawler.
        
        Args:
            max_depth: Maximum crawl depth from start URL
            max_pages: Maximum number of pages to crawl
            requests_per_second: Rate limit for requests
            timeout: Request timeout in seconds
            user_agent: User agent string for requests
        """
        self.max_depth = max_depth
        self.max_pages = max_pages
        self.timeout = timeout
        self.user_agent = user_agent
        
        self.rate_limiter = RateLimiter(requests_per_second)
        self.robots_cache: Dict[str, RobotFileParser] = {}
        
        # Crawl state
        self.visited_urls: Set[str] = set()
        self.crawled_urls: List[str] = []
        self.failed_urls: List[str] = []
        self._page_html: Dict[str, str] = {}
    
    async def crawl(
        self,
        start_url: str,
        allowed_domains: Optional[List[str]] = None
    ) -> List[str]:
        """Crawl website starting from start_url.
        
        Args:
            start_url: URL to start crawling from
            allowed_domains: List of allowed domains (defaults to start URL domain)
        
        Returns:
            List of successfully crawled URLs
        
        Raises:
            KnowledgeEngineError: If crawling fails
        """
        results = await self.crawl_with_content(start_url, allowed_domains)
        return [url for url, _ in results]

    async def crawl_with_content(
        self,
        start_url: str,
        allowed_domains: Optional[List[str]] = None
    ) -> List[tuple]:
        """Crawl website and return (url, html) pairs.
        
        Args:
            start_url: URL to start crawling from
            allowed_domains: List of allowed domains (defaults to start URL domain)
        
        Returns:
            List of (url, html) tuples for successfully crawled pages
        
        Raises:
            KnowledgeEngineError: If crawling fails
        """
        try:
            # Parse start URL
            parsed_start = urlparse(start_url)
            if not parsed_start.scheme or not parsed_start.netloc:
                raise KnowledgeEngineError(
                    f"Invalid start URL: {start_url}",
                    field="start_url"
                )
            
            # Set allowed domains
            if allowed_domains is None:
                allowed_domains = [parsed_start.netloc]
            
            logger.info(
                "crawl_started",
                start_url=start_url,
                max_depth=self.max_depth,
                max_pages=self.max_pages,
                allowed_domains=allowed_domains
            )
            
            # Reset state
            self.visited_urls.clear()
            self.crawled_urls.clear()
            self.failed_urls.clear()
            self._page_html: Dict[str, str] = {}  # url -> html cache
            
            # Create session
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                # Crawl recursively
                await self._crawl_recursive(
                    session,
                    start_url,
                    allowed_domains,
                    depth=0
                )
            
            logger.info(
                "crawl_completed",
                total_crawled=len(self.crawled_urls),
                total_failed=len(self.failed_urls),
                max_depth_reached=self.max_depth
            )
            
            # Return (url, html) pairs
            return [(url, self._page_html.get(url, "")) for url in self.crawled_urls]
            
        except Exception as e:
            logger.error("crawl_failed", error=str(e), start_url=start_url)
            raise KnowledgeEngineError(
                f"Failed to crawl {start_url}: {str(e)}",
                field="start_url"
            )
    
    async def _crawl_recursive(
        self,
        session: aiohttp.ClientSession,
        url: str,
        allowed_domains: List[str],
        depth: int
    ):
        """Recursively crawl pages.
        
        Args:
            session: aiohttp session
            url: Current URL to crawl
            allowed_domains: List of allowed domains
            depth: Current crawl depth
        """
        # Check if we should stop
        if depth > self.max_depth:
            return
        
        if len(self.crawled_urls) >= self.max_pages:
            logger.info("max_pages_reached", max_pages=self.max_pages)
            return
        
        # Normalize URL
        url = self._normalize_url(url)
        
        # Skip if already visited
        if url in self.visited_urls:
            return
        
        self.visited_urls.add(url)
        
        # Parse URL
        parsed = urlparse(url)
        
        # Check if domain is allowed
        if parsed.netloc not in allowed_domains:
            logger.debug("domain_not_allowed", url=url, domain=parsed.netloc)
            return
        
        # Check robots.txt
        if not await self._is_allowed_by_robots(session, url):
            logger.debug("blocked_by_robots", url=url)
            return
        
        # Rate limit
        await self.rate_limiter.acquire(parsed.netloc)
        
        # Fetch page
        try:
            html = await self._fetch_page(session, url)
            if html:
                self.crawled_urls.append(url)
                self._page_html[url] = html  # cache for reuse by init_runner
                logger.debug(
                    "page_crawled",
                    url=url,
                    depth=depth,
                    total=len(self.crawled_urls)
                )
                
                # Extract links and crawl recursively
                if depth < self.max_depth:
                    links = self._extract_links(html, url)
                    
                    # Crawl links (limit concurrency)
                    tasks = []
                    for link in links:
                        if len(self.crawled_urls) >= self.max_pages:
                            break
                        
                        task = self._crawl_recursive(
                            session,
                            link,
                            allowed_domains,
                            depth + 1
                        )
                        tasks.append(task)
                    
                    # Wait for all tasks (with some concurrency)
                    if tasks:
                        await asyncio.gather(*tasks, return_exceptions=True)
            
        except Exception as e:
            self.failed_urls.append(url)
            logger.warning("page_crawl_failed", url=url, error=str(e))
    
    async def _fetch_page(
        self,
        session: aiohttp.ClientSession,
        url: str
    ) -> Optional[str]:
        """Fetch page content.
        
        Args:
            session: aiohttp session
            url: URL to fetch
        
        Returns:
            HTML content or None if fetch failed
        """
        try:
            headers = {
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            }
            
            async with session.get(url, headers=headers) as response:
                # Check status code
                if response.status != 200:
                    logger.warning(
                        "fetch_failed_status",
                        url=url,
                        status=response.status
                    )
                    return None
                
                # Check content type
                content_type = response.headers.get("Content-Type", "")
                if "text/html" not in content_type.lower():
                    logger.debug(
                        "skipping_non_html",
                        url=url,
                        content_type=content_type
                    )
                    return None
                
                # Read content
                html = await response.text()
                return html
                
        except asyncio.TimeoutError:
            logger.warning("fetch_timeout", url=url)
            return None
        except aiohttp.ClientResponseError as e:
            logger.warning("fetch_error", url=url, error=str(e))
            return None
        except Exception as e:
            logger.warning("fetch_error", url=url, error=str(e))
            return None
    
    async def _is_allowed_by_robots(
        self,
        session: aiohttp.ClientSession,
        url: str
    ) -> bool:
        """Check if URL is allowed by robots.txt.
        
        Args:
            session: aiohttp session
            url: URL to check
        
        Returns:
            True if allowed, False otherwise
        """
        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"
        
        # Check cache
        if base_url in self.robots_cache:
            parser = self.robots_cache[base_url]
            return parser.can_fetch(self.user_agent, url)
        
        # Fetch robots.txt
        robots_url = urljoin(base_url, "/robots.txt")
        
        try:
            async with session.get(robots_url) as response:
                if response.status == 200:
                    robots_content = await response.text()
                    
                    # Parse robots.txt
                    parser = RobotFileParser()
                    parser.parse(robots_content.splitlines())
                    self.robots_cache[base_url] = parser
                    
                    return parser.can_fetch(self.user_agent, url)
                else:
                    # No robots.txt or error - allow by default
                    logger.debug(
                        "robots_txt_not_found",
                        base_url=base_url,
                        status=response.status
                    )
                    # Create permissive parser
                    parser = RobotFileParser()
                    parser.parse([])
                    self.robots_cache[base_url] = parser
                    return True
                    
        except Exception as e:
            logger.warning("robots_txt_fetch_failed", base_url=base_url, error=str(e))
            # Allow by default if robots.txt fetch fails
            parser = RobotFileParser()
            parser.parse([])
            self.robots_cache[base_url] = parser
            return True
    
    def _normalize_url(self, url: str) -> str:
        """Normalize URL by removing fragments and query parameters.
        
        Args:
            url: URL to normalize
        
        Returns:
            Normalized URL
        """
        parsed = urlparse(url)
        
        # Remove fragment and query
        normalized = urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            "",  # params
            "",  # query
            ""   # fragment
        ))
        
        # Remove trailing slash
        if normalized.endswith("/") and len(parsed.path) > 1:
            normalized = normalized[:-1]
        
        return normalized
    
    def _extract_links(self, html: str, base_url: str) -> List[str]:
        """Extract links from HTML.
        
        Args:
            html: HTML content
            base_url: Base URL for resolving relative links
        
        Returns:
            List of absolute URLs
        """
        from bs4 import BeautifulSoup
        
        try:
            soup = BeautifulSoup(html, "html.parser")
            links = []
            
            # Find all <a> tags with href
            for tag in soup.find_all("a", href=True):
                href = tag["href"]
                
                # Skip empty hrefs
                if not href or href.startswith("#"):
                    continue
                
                # Skip mailto, javascript, etc.
                if href.startswith(("mailto:", "javascript:", "tel:")):
                    continue
                
                # Resolve relative URLs
                absolute_url = urljoin(base_url, href)
                
                # Only include http/https URLs
                if absolute_url.startswith(("http://", "https://")):
                    links.append(absolute_url)
            
            return links
            
        except Exception as e:
            logger.warning("link_extraction_failed", base_url=base_url, error=str(e))
            return []
