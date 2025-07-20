from typing import Optional
from ...instance.models import (
    Resource as ResourceModel,
    CDPDescribeResponse,
    ChromeStartRequest,
    ChromeStartResponse,
)
from .base import Resource

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..instance.base import AsyncWrapper


class AsyncBrowserResource(Resource):
    def __init__(self, resource: ResourceModel, client: "AsyncWrapper"):
        super().__init__(resource)
        self.client = client

    async def start(self, width: int = 1920, height: int = 1080) -> CDPDescribeResponse:
        response = await self.client.request(
            "POST",
            "/resources/cdp/start",
            json=ChromeStartRequest(resolution=f"{width},{height}").model_dump(),
        )
        ChromeStartResponse(**response.json())
        return await self.describe()

    async def describe(self) -> CDPDescribeResponse:
        response = await self.client.request("GET", "/resources/cdp/describe")
        if response.status_code != 200:
            await self.start()
            response = await self.client.request("GET", "/resources/cdp/describe")
        return CDPDescribeResponse(**response.json())

    async def cdp_url(self) -> str:
        return (await self.describe()).cdp_browser_url

    async def devtools_url(self) -> str:
        return (await self.describe()).cdp_devtools_url
