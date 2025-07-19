import httpx
from typing import Dict, Any, Optional
import json

from .models import InstanceResponse
from .exceptions import (
    FleetAPIError,
    FleetAuthenticationError,
    FleetRateLimitError,
    FleetInstanceLimitError,
    FleetTimeoutError,
)


class EnvironmentBase(InstanceResponse):
    @property
    def manager_url(self) -> str:
        return f"{self.urls.manager.api}"


class BaseWrapper:
    def __init__(self, *, api_key: Optional[str], base_url: Optional[str]):
        if api_key is None:
            raise ValueError("api_key is required")
        self.api_key = api_key
        if base_url is None:
            base_url = "https://orchestrator.fleetai.com"
        self.base_url = base_url

    def get_headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {
            "X-Fleet-SDK-Language": "Python",
            "X-Fleet-SDK-Version": "1.0.0",
        }
        headers["Authorization"] = f"Bearer {self.api_key}"
        return headers


class AsyncWrapper(BaseWrapper):
    def __init__(self, *, httpx_client: httpx.AsyncClient, **kwargs):
        super().__init__(**kwargs)
        self.httpx_client = httpx_client

    async def request(
        self,
        method: str,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Any] = None,
        base_url: Optional[str] = None,
        **kwargs,
    ) -> httpx.Response:
        base_url = base_url or self.base_url
        try:
            response = await self.httpx_client.request(
                method,
                f"{base_url}{url}",
                headers=self.get_headers(),
                params=params,
                json=json,
                **kwargs,
            )

            # Check for HTTP errors
            if response.status_code >= 400:
                self._handle_error_response(response)

            return response
        except httpx.TimeoutException as e:
            raise FleetTimeoutError(f"Request timed out: {str(e)}")
        except httpx.RequestError as e:
            raise FleetAPIError(f"Request failed: {str(e)}")

    def _handle_error_response(self, response: httpx.Response) -> None:
        """Handle HTTP error responses and convert to appropriate Fleet exceptions."""
        status_code = response.status_code

        # Try to parse error response as JSON
        try:
            error_data = response.json()
            detail = error_data.get("detail", response.text)

            # Handle structured error responses
            if isinstance(detail, dict):
                error_type = detail.get("error_type", "")
                error_message = detail.get("message", str(detail))

                if error_type == "instance_limit_exceeded":
                    raise FleetInstanceLimitError(
                        error_message,
                        running_instances=detail.get("running_instances"),
                        instance_limit=detail.get("instance_limit"),
                    )
                else:
                    error_message = detail.get("message", str(detail))
            else:
                error_message = detail

        except (json.JSONDecodeError, ValueError):
            error_message = response.text
            error_data = None

        # Handle specific error types
        if status_code == 401:
            raise FleetAuthenticationError(error_message)
        elif status_code == 429:
            # Check if it's an instance limit error vs rate limit error (fallback for unstructured errors)
            if "instance limit" in error_message.lower():
                # Try to extract instance counts from the error message
                running_instances = None
                instance_limit = None
                if (
                    "You have" in error_message
                    and "running instances out of a maximum of" in error_message
                ):
                    try:
                        # Extract numbers from message like "You have 5 running instances out of a maximum of 10"
                        parts = error_message.split("You have ")[1].split(
                            " running instances out of a maximum of "
                        )
                        if len(parts) == 2:
                            running_instances = int(parts[0])
                            instance_limit = int(parts[1].split(".")[0])
                    except (IndexError, ValueError):
                        pass

                raise FleetInstanceLimitError(
                    error_message,
                    running_instances=running_instances,
                    instance_limit=instance_limit,
                )
            else:
                raise FleetRateLimitError(error_message)
        else:
            raise FleetAPIError(
                error_message,
                status_code=status_code,
                response_data=error_data if "error_data" in locals() else None,
            )
