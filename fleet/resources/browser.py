from typing import Optional

from ..env.models import (
    Resource as ResourceModel,
    CDPDescribeResponse,
    ChromeStartRequest,
    ChromeStartResponse,
)
from .base import Resource

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..env.base import AsyncWrapper


class AsyncBrowserResource(Resource):
    def __init__(self, resource: ResourceModel, client: "AsyncWrapper"):
        super().__init__(resource)
        self.client = client

    async def start(
        self, start_request: Optional[ChromeStartRequest] = None
    ) -> ChromeStartResponse:
        response = await self.client.request(
            "POST",
            "/resources/cdp/start",
            json=start_request.model_dump() if start_request else None,
        )
        return ChromeStartResponse(**response.json())

    async def describe(self) -> CDPDescribeResponse:
        response = await self.client.request("GET", "/resources/cdp/describe")
        return CDPDescribeResponse(**response.json())
