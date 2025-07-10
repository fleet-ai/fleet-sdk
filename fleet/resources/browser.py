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
    from ..instance.base import Wrapper


class BrowserResource(Resource):
    def __init__(self, resource: ResourceModel, client: "Wrapper"):
        super().__init__(resource)
        self.client = client
        self._describe: Optional[CDPDescribeResponse] = None

    def start(self, width: int = 1920, height: int = 1080) -> CDPDescribeResponse:
        response = self.client.request(
            "POST",
            "/resources/cdp/start",
            json=ChromeStartRequest(resolution=f"{width},{height}").model_dump(),
        )
        ChromeStartResponse(**response.json())
        return self.describe()

    def describe(self) -> CDPDescribeResponse:
        if self._describe is None:
            response = self.client.request("GET", "/resources/cdp/describe")
            if response.status_code != 200:
                self.start()
                response = self.client.request("GET", "/resources/cdp/describe")
            self._describe = CDPDescribeResponse(**response.json())
        return self._describe

    def cdp_url(self) -> str:
        return self.describe().cdp_browser_url

    def devtools_url(self) -> str:
        return self.describe().cdp_devtools_url
