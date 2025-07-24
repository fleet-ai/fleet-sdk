from typing import Optional
from ..instance.models import (
    Resource as ResourceModel,
    CDPDescribeResponse,
    ChromeStartRequest,
    ChromeStartResponse,
)
from .base import Resource

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..instance.base import SyncWrapper


class BrowserResource(Resource):
    def __init__(self, resource: ResourceModel, client: "SyncWrapper"):
        super().__init__(resource)
        self.client = client
    
    def start(self, width: int = 1920, height: int = 1080) -> CDPDescribeResponse:
        """Start browser and return CDP information."""
        request = ChromeStartRequest(resolution=f"{width}x{height}")
        response = self.client.request("POST", "/resources/cdp/start", json=request.model_dump())
        
        # After starting, get the CDP information via describe
        return self.describe()
        
    def describe(self) -> CDPDescribeResponse:
        response = self.client.request("GET", "/resources/cdp/describe")
        if response.status_code != 200:
            self.start()
            response = self.client.request("GET", "/resources/cdp/describe")
        return CDPDescribeResponse(**response.json())

    def cdp_url(self) -> str:
        return (self.describe()).cdp_browser_url

    def devtools_url(self) -> str:
        return (self.describe()).cdp_devtools_url
