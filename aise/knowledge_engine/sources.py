# aise/knowledge_engine/sources.py
"""Pre-configured documentation registry for official sources.

This module provides a registry of official documentation URLs for common
platforms and tools, making it easy for users to enable knowledge sources
without manually finding URLs.

Example usage:
    >>> from aise.knowledge_engine.sources import DocumentationRegistry
    >>> 
    >>> registry = DocumentationRegistry()
    >>> sources = registry.list_sources()
    >>> 
    >>> # Get specific source
    >>> aws_source = registry.get_source("aws")
    >>> print(aws_source.url)
"""

from dataclasses import dataclass, asdict
from typing import List, Optional, Dict, Any
from enum import Enum


class SourceCategory(Enum):
    """Categories for documentation sources."""
    CLOUD_PROVIDER = "cloud_provider"
    CONTAINER = "container"
    ORCHESTRATION = "orchestration"
    INFRASTRUCTURE = "infrastructure"
    VERSION_CONTROL = "version_control"
    DATABASE = "database"
    MONITORING = "monitoring"
    OTHER = "other"


@dataclass
class DocumentationSource:
    """Represents a pre-configured documentation source.
    
    Attributes:
        name: Unique identifier (e.g., "aws", "kubernetes")
        display_name: Human-readable name
        url: Base URL for documentation
        description: Brief description of the documentation
        category: Source category
        estimated_size_mb: Estimated size in megabytes
        estimated_pages: Estimated number of pages
        recommended: Whether this source is recommended for most users
        metadata: Additional metadata
    """
    name: str
    display_name: str
    url: str
    description: str
    category: SourceCategory
    estimated_size_mb: int
    estimated_pages: int
    recommended: bool = True
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        """Set default values after initialization."""
        if self.metadata is None:
            self.metadata = {}
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary.
        
        Returns:
            Dictionary representation
        """
        data = asdict(self)
        data['category'] = self.category.value
        return data


class DocumentationRegistry:
    """Registry of pre-configured official documentation sources.
    
    Provides easy access to official documentation URLs for common platforms
    and tools without requiring users to manually find and configure URLs.
    
    Example:
        >>> registry = DocumentationRegistry()
        >>> aws = registry.get_source("aws")
        >>> all_sources = registry.list_sources()
        >>> cloud_sources = registry.list_by_category(SourceCategory.CLOUD_PROVIDER)
    """
    
    def __init__(self):
        """Initialize documentation registry with pre-configured sources."""
        self._sources: Dict[str, DocumentationSource] = {}
        self._load_default_sources()
    
    def _load_default_sources(self) -> None:
        """Load default pre-configured documentation sources."""
        default_sources = [
            # Cloud Providers
            DocumentationSource(
                name="aws",
                display_name="Amazon Web Services (AWS)",
                url="https://docs.aws.amazon.com/general/latest/gr/",
                description="Official AWS General Reference documentation covering common concepts and services",
                category=SourceCategory.CLOUD_PROVIDER,
                estimated_size_mb=500,
                estimated_pages=10000,
                recommended=True,
                metadata={"provider": "amazon", "services": ["ec2", "s3", "lambda", "rds", "vpc"]}
            ),

            DocumentationSource(
                name="aws-linux",
                display_name="AWS Linux Documentation",
                url="https://docs.aws.amazon.com/linux/al2023/ug/",
                description="Official AWS Linux 2023 User Guide",
                category=SourceCategory.CLOUD_PROVIDER,
                estimated_size_mb=50,
                estimated_pages=500,
                recommended=True,
                metadata={"provider": "amazon", "topics": ["amazon-linux", "al2", "al2023"]}
            ),
            DocumentationSource(
                name="ubuntu",
                display_name="Ubuntu Documentation",
                url="https://ubuntu.com/server/docs/",
                description="Official Ubuntu Server documentation",
                category=SourceCategory.OTHER,
                estimated_size_mb=80,
                estimated_pages=1000,
                recommended=True,
                metadata={"topics": ["installation", "server", "desktop", "packages"]}
            ),
            DocumentationSource(
                name="azure",
                display_name="Microsoft Azure",
                url="https://learn.microsoft.com/en-us/azure/",
                description="Official Azure documentation for compute, storage, networking, and Azure services",
                category=SourceCategory.CLOUD_PROVIDER,
                estimated_size_mb=400,
                estimated_pages=8000,
                recommended=True,
                metadata={"provider": "microsoft", "services": ["vm", "storage", "functions", "sql"]}
            ),
            DocumentationSource(
                name="gcp",
                display_name="Google Cloud Platform (GCP)",
                url="https://cloud.google.com/compute/docs/",
                description="Official GCP Compute Engine documentation covering VMs, networking, and GCP services",
                category=SourceCategory.CLOUD_PROVIDER,
                estimated_size_mb=350,
                estimated_pages=7000,
                recommended=True,
                metadata={"provider": "google", "services": ["compute", "storage", "functions", "sql"]}
            ),
            
            # Container & Orchestration
            DocumentationSource(
                name="kubernetes",
                display_name="Kubernetes",
                url="https://kubernetes.io/docs/concepts/",
                description="Official Kubernetes documentation for container orchestration",
                category=SourceCategory.ORCHESTRATION,
                estimated_size_mb=100,
                estimated_pages=2000,
                recommended=True,
                metadata={"topics": ["pods", "deployments", "services", "ingress", "storage"]}
            ),
            DocumentationSource(
                name="docker",
                display_name="Docker",
                url="https://docs.docker.com/",
                description="Official Docker documentation for containerization",
                category=SourceCategory.CONTAINER,
                estimated_size_mb=80,
                estimated_pages=1500,
                recommended=True,
                metadata={"topics": ["containers", "images", "compose", "swarm", "networking"]}
            ),
            
            # Infrastructure as Code
            DocumentationSource(
                name="terraform",
                display_name="Terraform",
                url="https://developer.hashicorp.com/terraform/docs",
                description="Official Terraform documentation for infrastructure as code",
                category=SourceCategory.INFRASTRUCTURE,
                estimated_size_mb=60,
                estimated_pages=1200,
                recommended=True,
                metadata={"topics": ["providers", "resources", "modules", "state", "cli"]}
            ),
            DocumentationSource(
                name="ansible",
                display_name="Ansible",
                url="https://docs.ansible.com/projects/ansible/latest/",
                description="Official Ansible documentation for configuration management",
                category=SourceCategory.INFRASTRUCTURE,
                estimated_size_mb=70,
                estimated_pages=1400,
                recommended=False,
                metadata={"topics": ["playbooks", "modules", "inventory", "roles"]}
            ),
            
            # Version Control
            DocumentationSource(
                name="git",
                display_name="Git",
                url="https://git-scm.com/doc",
                description="Official Git documentation for version control",
                category=SourceCategory.VERSION_CONTROL,
                estimated_size_mb=30,
                estimated_pages=500,
                recommended=True,
                metadata={"topics": ["commands", "branching", "merging", "remote", "workflow"]}
            ),
            
            # Databases
            DocumentationSource(
                name="postgresql",
                display_name="PostgreSQL",
                url="https://www.postgresql.org/docs/current/",
                description="Official PostgreSQL documentation",
                category=SourceCategory.DATABASE,
                estimated_size_mb=50,
                estimated_pages=1000,
                recommended=False,
                metadata={"topics": ["sql", "administration", "performance", "replication"]}
            ),
            DocumentationSource(
                name="redis",
                display_name="Redis",
                url="https://redis.io/docs/",
                description="Official Redis documentation for in-memory data store",
                category=SourceCategory.DATABASE,
                estimated_size_mb=40,
                estimated_pages=800,
                recommended=False,
                metadata={"topics": ["commands", "data-types", "persistence", "clustering"]}
            ),
            
            # Monitoring & Observability
            DocumentationSource(
                name="prometheus",
                display_name="Prometheus",
                url="https://prometheus.io/docs/",
                description="Official Prometheus documentation for monitoring",
                category=SourceCategory.MONITORING,
                estimated_size_mb=35,
                estimated_pages=700,
                recommended=False,
                metadata={"topics": ["metrics", "queries", "alerting", "exporters"]}
            ),
            DocumentationSource(
                name="grafana",
                display_name="Grafana",
                url="https://grafana.com/docs/grafana/latest/",
                description="Official Grafana documentation for visualization",
                category=SourceCategory.MONITORING,
                estimated_size_mb=45,
                estimated_pages=900,
                recommended=False,
                metadata={"topics": ["dashboards", "panels", "datasources", "alerting"]}
            ),
        ]
        
        # Add sources to registry
        for source in default_sources:
            self._sources[source.name] = source
    
    def get_source(self, name: str) -> Optional[DocumentationSource]:
        """Get documentation source by name.
        
        Args:
            name: Source name (e.g., "aws", "kubernetes")
        
        Returns:
            DocumentationSource or None if not found
        """
        return self._sources.get(name)
    
    def list_sources(self, recommended_only: bool = False) -> List[DocumentationSource]:
        """List all documentation sources.
        
        Args:
            recommended_only: If True, return only recommended sources
        
        Returns:
            List of DocumentationSource objects
        """
        sources = list(self._sources.values())
        
        if recommended_only:
            sources = [s for s in sources if s.recommended]
        
        return sorted(sources, key=lambda s: s.display_name)
    
    def list_by_category(self, category: SourceCategory) -> List[DocumentationSource]:
        """List documentation sources by category.
        
        Args:
            category: Source category to filter by
        
        Returns:
            List of DocumentationSource objects in the category
        """
        return [
            source for source in self._sources.values()
            if source.category == category
        ]
    
    def search_sources(self, query: str) -> List[DocumentationSource]:
        """Search documentation sources by name or description.
        
        Args:
            query: Search query (case-insensitive)
        
        Returns:
            List of matching DocumentationSource objects
        """
        query_lower = query.lower()
        
        return [
            source for source in self._sources.values()
            if query_lower in source.name.lower()
            or query_lower in source.display_name.lower()
            or query_lower in source.description.lower()
        ]
    
    def add_custom_source(self, source: DocumentationSource) -> None:
        """Add a custom documentation source to the registry.
        
        Args:
            source: DocumentationSource to add
        
        Raises:
            ValueError: If source name already exists
        """
        if source.name in self._sources:
            raise ValueError(f"Source '{source.name}' already exists in registry")
        
        self._sources[source.name] = source
    
    def remove_source(self, name: str) -> bool:
        """Remove a documentation source from the registry.
        
        Args:
            name: Source name to remove
        
        Returns:
            True if removed, False if not found
        """
        if name in self._sources:
            del self._sources[name]
            return True
        return False
    
    def get_total_estimated_size(self, source_names: List[str]) -> int:
        """Get total estimated size for multiple sources.
        
        Args:
            source_names: List of source names
        
        Returns:
            Total estimated size in megabytes
        """
        total = 0
        for name in source_names:
            source = self.get_source(name)
            if source:
                total += source.estimated_size_mb
        return total
    
    def get_recommended_sources(self) -> List[DocumentationSource]:
        """Get list of recommended sources for most users.
        
        Returns:
            List of recommended DocumentationSource objects
        """
        return self.list_sources(recommended_only=True)


# Global registry instance
_registry: Optional[DocumentationRegistry] = None


def get_registry() -> DocumentationRegistry:
    """Get global documentation registry instance.
    
    Returns:
        DocumentationRegistry instance
    """
    global _registry
    
    if _registry is None:
        _registry = DocumentationRegistry()
    
    return _registry


# Simple list format for compatibility with init_runner
REGISTERED_SOURCES: List[Dict[str, str]] = [
    # AWS: point to specific guides that have toc-contents.json
    # The root docs.aws.amazon.com/ is a JS-rendered landing page with no crawlable links
    {"name": "aws", "url": "https://docs.aws.amazon.com/general/latest/gr/"},
    {"name": "aws-linux", "url": "https://docs.aws.amazon.com/linux/al2023/ug/"},
    {"name": "azure", "url": "https://learn.microsoft.com/en-us/azure/"},
    {"name": "ubuntu", "url": "https://ubuntu.com/server/docs/"},
    {"name": "git", "url": "https://git-scm.com/doc"},
    {"name": "kubernetes", "url": "https://kubernetes.io/docs/concepts/"},
    {"name": "gcp", "url": "https://cloud.google.com/compute/docs/"},
    {"name": "docker", "url": "https://docs.docker.com/"},
    {"name": "terraform", "url": "https://developer.hashicorp.com/terraform/docs"},
    {"name": "ibm-cloud", "url": "https://cloud.ibm.com/docs"},
    {"name": "oracle", "url": "https://docs.oracle.com/en-us/iaas/Content/home.htm"},
]


def get_source(name: str) -> Optional[Dict[str, str]]:
    """Get source dict by name from REGISTERED_SOURCES.
    
    Args:
        name: Source name (e.g., "aws", "kubernetes")
    
    Returns:
        Source dict with 'name' and 'url' keys, or None if not found
    """
    for source in REGISTERED_SOURCES:
        if source["name"] == name:
            return source
    return None
