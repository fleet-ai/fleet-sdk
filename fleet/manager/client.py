import httpx
from typing import Optional, List, Dict, Any

from .base import SyncWrapper, AsyncWrapper
from .models import ResetResponse, Resource, ResourceType
from .facets import SQLiteFacet, AsyncSQLiteFacet, CDPFacet, AsyncCDPFacet


class Manager:
    def __init__(self, url: str, httpx_client: Optional[httpx.Client] = None):
        self.base_url = url
        self.client = SyncWrapper(
            url=self.base_url, httpx_client=httpx_client or httpx.Client()
        )
        self._facets: Dict[str, Any] = {}
        self._resources_cache: Optional[List[Resource]] = None
        
        # Facet registry mapping resource types to facet classes
        self._facet_registry = {
            ResourceType.sqlite: SQLiteFacet,
            ResourceType.cdp: CDPFacet,
        }
        
        # Initialize type-based facet collections
        self._sqlite: Dict[str, SQLiteFacet] = {}
        self._cdp: Dict[str, CDPFacet] = {}
        
        # Load facets on initialization
        self._load_facets()

    def reset(self) -> ResetResponse:
        response = self.client.request("POST", "/reset")
        return ResetResponse(**response.json())

    @property
    def resources(self) -> List[Resource]:
        """Get list of available resources."""
        if self._resources_cache is None:
            response = self.client.request("GET", "/resources")
            self._resources_cache = [Resource(**resource) for resource in response.json()["resources"]]
        return self._resources_cache

    def _load_facets(self) -> None:
        """Load facets dynamically based on available resources."""
        for resource in self.resources:
            facet_class = self._facet_registry.get(resource.type)
            if facet_class:
                facet = facet_class(resource.name, self.client)
                self._facets[resource.name] = facet
                
                # Also set as attribute for direct access
                setattr(self, resource.name, facet)
                
                # Add to type-specific collection
                if resource.type == ResourceType.sqlite:
                    self._sqlite[resource.name] = facet
                elif resource.type == ResourceType.cdp:
                    self._cdp[resource.name] = facet
    
    def get_facet(self, resource_name: str) -> Optional[Any]:
        """Get a facet by resource name."""
        return self._facets.get(resource_name)
    
    def get_sqlite_facets(self) -> Dict[str, SQLiteFacet]:
        """Get all SQLite facets indexed by name."""
        return self._sqlite
    
    def get_cdp_facets(self) -> Dict[str, CDPFacet]:
        """Get all CDP/browser facets indexed by name."""
        return self._cdp
    
    def refresh_facets(self) -> None:
        """Refresh the facets by re-fetching resources."""
        self._resources_cache = None
        self._facets.clear()
        self._sqlite.clear()
        self._cdp.clear()
        
        # Remove old facet attributes
        for resource in self.resources:
            if hasattr(self, resource.name):
                delattr(self, resource.name)
        self._load_facets()


class AsyncManager:
    def __init__(self, url: str, httpx_client: Optional[httpx.AsyncClient] = None):
        self.base_url = url
        self.client = AsyncWrapper(
            url=self.base_url, httpx_client=httpx_client or httpx.AsyncClient()
        )
        self._facets: Dict[str, Any] = {}
        self._resources_cache: Optional[List[Resource]] = None
        
        # Facet registry mapping resource types to facet classes
        self._facet_registry = {
            ResourceType.sqlite: AsyncSQLiteFacet,
            ResourceType.cdp: AsyncCDPFacet,
        }
        
        # Initialize type-based facet collections
        self._sqlite: Dict[str, AsyncSQLiteFacet] = {}
        self._cdp: Dict[str, AsyncCDPFacet] = {}

    async def __aenter__(self):
        """Async context manager entry - load facets."""
        await self._load_facets()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        return None

    async def reset(self) -> ResetResponse:
        response = await self.client.request("POST", "/reset")
        return ResetResponse(**response.json())

    async def get_resources(self) -> List[Resource]:
        """Get list of available resources."""
        if self._resources_cache is None:
            response = await self.client.request("GET", "/resources")
            self._resources_cache = [Resource(**resource) for resource in response.json()["resources"]]
        return self._resources_cache

    async def _load_facets(self) -> None:
        """Load facets dynamically based on available resources."""
        resources = await self.get_resources()
        for resource in resources:
            facet_class = self._facet_registry.get(resource.type)
            if facet_class:
                facet = facet_class(resource.name, self.client)
                self._facets[resource.name] = facet
                
                # Also set as attribute for direct access
                setattr(self, resource.name, facet)
                
                # Add to type-specific collection
                if resource.type == ResourceType.sqlite:
                    self._sqlite[resource.name] = facet
                elif resource.type == ResourceType.cdp:
                    self._cdp[resource.name] = facet
    
    def get_facet(self, resource_name: str) -> Optional[Any]:
        """Get a facet by resource name."""
        return self._facets.get(resource_name)
    
    def get_sqlite_facets(self) -> Dict[str, AsyncSQLiteFacet]:
        """Get all SQLite facets indexed by name."""
        return self._sqlite
    
    def get_cdp_facets(self) -> Dict[str, AsyncCDPFacet]:
        """Get all CDP/browser facets indexed by name."""
        return self._cdp
    
    async def refresh_facets(self) -> None:
        """Refresh the facets by re-fetching resources."""
        self._resources_cache = None
        self._facets.clear()
        self._sqlite.clear()
        self._cdp.clear()
        
        # Remove old facet attributes
        resources = await self.get_resources()
        for resource in resources:
            if hasattr(self, resource.name):
                delattr(self, resource.name)
        await self._load_facets()
