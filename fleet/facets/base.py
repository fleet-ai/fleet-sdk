"""Fleet SDK Base Facet Classes."""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from ..env.base import Environment


class Facet(ABC):
    """Base class for all facets in Fleet environments."""
    
    def __init__(self, uri: str, environment: "Environment"):
        self.uri = uri
        self.environment = environment
        self._parsed_uri = urlparse(uri)
        self._scheme = self._parsed_uri.scheme
        self._netloc = self._parsed_uri.netloc
        self._path = self._parsed_uri.path
        self._params = self._parsed_uri.params
        self._query = self._parsed_uri.query
        self._fragment = self._parsed_uri.fragment
        
    @property
    def scheme(self) -> str:
        """Get the URI scheme (e.g., 'sqlite', 'browser', 'file')."""
        return self._scheme
    
    @property
    def netloc(self) -> str:
        """Get the URI network location."""
        return self._netloc
    
    @property
    def path(self) -> str:
        """Get the URI path."""
        return self._path
    
    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the facet."""
        pass
    
    @abstractmethod
    async def close(self) -> None:
        """Close the facet and clean up resources."""
        pass
    
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(uri='{self.uri}')"


class DatabaseFacet(Facet):
    """Base class for database facets."""
    
    @abstractmethod
    async def exec(self, query: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """Execute a database query.
        
        Args:
            query: SQL query to execute
            params: Query parameters
            
        Returns:
            Query result
        """
        pass
    
    @abstractmethod
    async def fetch(self, query: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """Fetch results from a database query.
        
        Args:
            query: SQL query to execute
            params: Query parameters
            
        Returns:
            Query results
        """
        pass


class BrowserFacet(Facet):
    """Base class for browser facets."""
    
    @abstractmethod
    async def get_dom(self) -> Dict[str, Any]:
        """Get the current DOM structure.
        
        Returns:
            DOM structure as dictionary
        """
        pass
    
    @abstractmethod
    async def get_element(self, selector: str) -> Optional[Dict[str, Any]]:
        """Get an element by CSS selector.
        
        Args:
            selector: CSS selector
            
        Returns:
            Element data or None if not found
        """
        pass
    
    @abstractmethod
    async def get_elements(self, selector: str) -> list[Dict[str, Any]]:
        """Get elements by CSS selector.
        
        Args:
            selector: CSS selector
            
        Returns:
            List of element data
        """
        pass


class FileFacet(Facet):
    """Base class for file system facets."""
    
    @abstractmethod
    async def read(self, path: str) -> bytes:
        """Read file contents.
        
        Args:
            path: File path
            
        Returns:
            File contents as bytes
        """
        pass
    
    @abstractmethod
    async def write(self, path: str, content: bytes) -> None:
        """Write file contents.
        
        Args:
            path: File path
            content: Content to write
        """
        pass
    
    @abstractmethod
    async def list_dir(self, path: str) -> list[str]:
        """List directory contents.
        
        Args:
            path: Directory path
            
        Returns:
            List of file/directory names
        """
        pass
    
    @abstractmethod
    async def exists(self, path: str) -> bool:
        """Check if file or directory exists.
        
        Args:
            path: File or directory path
            
        Returns:
            True if exists, False otherwise
        """
        pass


class APIFacet(Facet):
    """Base class for API facets."""
    
    @abstractmethod
    async def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """Make a GET request.
        
        Args:
            path: API endpoint path
            params: Query parameters
            
        Returns:
            API response
        """
        pass
    
    @abstractmethod
    async def post(self, path: str, data: Optional[Dict[str, Any]] = None) -> Any:
        """Make a POST request.
        
        Args:
            path: API endpoint path
            data: Request data
            
        Returns:
            API response
        """
        pass
    
    @abstractmethod
    async def put(self, path: str, data: Optional[Dict[str, Any]] = None) -> Any:
        """Make a PUT request.
        
        Args:
            path: API endpoint path
            data: Request data
            
        Returns:
            API response
        """
        pass
    
    @abstractmethod
    async def delete(self, path: str) -> Any:
        """Make a DELETE request.
        
        Args:
            path: API endpoint path
            
        Returns:
            API response
        """
        pass 