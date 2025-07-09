"""Manager Facets - Database and other resource interfaces."""

from typing import Optional, List, Any, TYPE_CHECKING
from ..facets.base import Resource
from .models import (
    DescribeResponse,
    QueryRequest,
    QueryResponse,
    BrowserDescribeResponse,
    Resource as ResourceModel,
)

if TYPE_CHECKING:
    from .base import AsyncWrapper


class AsyncSQLiteResource(Resource):
    def __init__(self, resource: ResourceModel, client: "AsyncWrapper"):
        super().__init__(resource)
        self.client = client

    async def describe(self) -> DescribeResponse:
        """Describe the SQLite database schema."""
        response = await self.client.request(
            "GET", f"/resource/sqlite/{self.resource.name}/describe"
        )
        return DescribeResponse(**response.json())

    async def query(
        self, query: str, args: Optional[List[Any]] = None
    ) -> QueryResponse:
        return await self._query(query, args, read_only=True)

    async def exec(self, query: str, args: Optional[List[Any]] = None) -> QueryResponse:
        return await self._query(query, args, read_only=False)

    async def _query(
        self, query: str, args: Optional[List[Any]] = None, read_only: bool = True
    ) -> QueryResponse:
        request = QueryRequest(query=query, args=args, read_only=read_only)
        response = await self.client.request(
            "POST",
            f"/resource/sqlite/{self.resource.name}/query",
            json=request.model_dump(),
        )
        return QueryResponse(**response.json())


class AsyncBrowserResource(Resource):
    def __init__(self, resource: ResourceModel, client: "AsyncWrapper"):
        super().__init__(resource)
        self.client = client

    async def describe(self) -> BrowserDescribeResponse:
        response = await self.client.request("GET", "/resource/cdp/describe")
        return BrowserDescribeResponse(**response.json())
