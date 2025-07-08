"""Fleet SDK Base Facet Classes."""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional, TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from ..env.base import Environment


class Facet(ABC):
    """Base class for all facets in Fleet environments."""

    def __init__(self, uri: str):
        self.uri = uri
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

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(uri='{self.uri}')"
