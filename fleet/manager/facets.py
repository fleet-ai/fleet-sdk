"""Manager Facets - Database and other resource interfaces."""

from typing import Optional, List, Any, TYPE_CHECKING
from ..facets.base import Facet
from .models import DescribeResponse, QueryRequest, QueryResponse, ResourcesResponse

if TYPE_CHECKING:
    from .base import SyncWrapper, AsyncWrapper


class SQLiteFacet(Facet):
    """SQLite database facet for manager resources."""

    def __init__(self, resource_name: str, client: "SyncWrapper"):
        super().__init__(scheme="sqlite")
        self.resource_name = resource_name
        self.client = client

    def describe(self) -> DescribeResponse:
        """Describe the SQLite database schema."""
        response = self.client.request(
            "GET", f"/resources/{self.resource_name}/describe"
        )
        return DescribeResponse(**response.json())

    def query(
        self, query: str, args: Optional[List[Any]] = None, read_only: bool = True
    ) -> QueryResponse:
        """Execute a SQL query."""
        request = QueryRequest(query=query, args=args, read_only=read_only)
        response = self.client.request(
            "POST", f"/resources/{self.resource_name}/query", json=request.model_dump()
        )
        return QueryResponse(**response.json())


class AsyncSQLiteFacet(Facet):
    """Async SQLite database facet for manager resources."""

    def __init__(self, resource_name: str, client: "AsyncWrapper"):
        super().__init__(scheme="sqlite")
        self.resource_name = resource_name
        self.client = client

    async def describe(self, resource_name: str) -> DescribeResponse:
        """Describe the SQLite database schema."""
        response = await self.client.request(
            "GET", f"/resource/sqlite/{resource_name}/describe"
        )
        return DescribeResponse(**response.json())

    async def query(
        self, query: str, args: Optional[List[Any]] = None, read_only: bool = True
    ) -> QueryResponse:
        """Execute a SQL query."""
        request = QueryRequest(query=query, args=args, read_only=read_only)
        response = await self.client.request(
            "POST", f"/resources/{self.resource_name}/query", json=request.model_dump()
        )
        return QueryResponse(**response.json())
