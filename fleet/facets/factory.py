"""Fleet SDK Facet Factory."""

from typing import TYPE_CHECKING
from urllib.parse import urlparse

from .base import Facet
from ..exceptions import FleetFacetError

if TYPE_CHECKING:
    from ..env.base import Environment


def create_facet(uri: str, environment: "Environment") -> Facet:
    """Create a facet based on the URI scheme.
    
    Args:
        uri: URI identifying the facet (e.g., 'sqlite://crm', 'browser://dom')
        environment: Environment instance
        
    Returns:
        Facet instance
        
    Raises:
        NotImplementedError: Facet implementations are not yet available
    """
    parsed = urlparse(uri)
    scheme = parsed.scheme.lower()
    
    raise NotImplementedError(f"Facet implementation for scheme '{scheme}' not yet available") 