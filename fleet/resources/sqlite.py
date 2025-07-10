from typing import Any, List, Optional
from ..instance.models import Resource as ResourceModel
from ..instance.models import DescribeResponse, QueryRequest, QueryResponse
from .base import Resource

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..instance.base import Wrapper


class SQLiteResource(Resource):
    def __init__(self, resource: ResourceModel, client: "Wrapper"):
        super().__init__(resource)
        self.client = client

    def describe(self) -> DescribeResponse:
        """Describe the SQLite database schema."""
        response = self.client.request(
            "GET", f"/resources/sqlite/{self.resource.name}/describe"
        )
        return DescribeResponse(**response.json())

    def query(
        self, query: str, args: Optional[List[Any]] = None
    ) -> QueryResponse:
        return self._query(query, args, read_only=True)

    def exec(self, query: str, args: Optional[List[Any]] = None) -> QueryResponse:
        return self._query(query, args, read_only=False)

    def _query(
        self, query: str, args: Optional[List[Any]] = None, read_only: bool = True
    ) -> QueryResponse:
        request = QueryRequest(query=query, args=args, read_only=read_only)
        response = self.client.request(
            "POST",
            f"/resources/sqlite/{self.resource.name}/query",
            json=request.model_dump(),
        )
        return QueryResponse(**response.json())
