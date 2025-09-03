import httpx
from typing import Dict, Any, Optional
import json
import logging

from .models import InstanceResponse
from .config import GLOBAL_BASE_URL
from .exceptions import (
    FleetAPIError,
    FleetAuthenticationError,
    FleetRateLimitError,
    FleetInstanceLimitError,
    FleetTimeoutError,
    FleetTeamNotFoundError,
    FleetEnvironmentAccessError,
    FleetRegionError,
    FleetEnvironmentNotFoundError,
    FleetVersionNotFoundError,
    FleetBadRequestError,
    FleetPermissionError,
)

logger = logging.getLogger(__name__)


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
            base_url = GLOBAL_BASE_URL
        self.base_url = base_url

    def get_headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {
            "X-Fleet-SDK-Language": "Python",
            "X-Fleet-SDK-Version": "1.0.0",
        }
        headers["Authorization"] = f"Bearer {self.api_key}"
        # Debug log
        import logging

        logger = logging.getLogger(__name__)
        logger.debug(f"Headers being sent: {headers}")
        return headers


class SyncWrapper(BaseWrapper):
    def __init__(self, *, httpx_client: httpx.Client, **kwargs):
        super().__init__(**kwargs)
        self.httpx_client = httpx_client

    def request(
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
            response = self.httpx_client.request(
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

        # Debug log 500 errors
        if status_code == 500:
            logger.error(f"Got 500 error from {response.url}")
            logger.error(f"Response text: {response.text}")

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
        elif status_code == 403:
            # Handle 403 errors - instance limit, permissions, team not found
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
            elif "team not found" in error_message.lower():
                raise FleetTeamNotFoundError(error_message)
            elif (
                "does not have permission" in error_message.lower()
                and "environment" in error_message.lower()
            ):
                # Extract environment key from error message if possible
                env_key = None
                if "'" in error_message:
                    # Look for quoted environment key
                    parts = error_message.split("'")
                    if len(parts) >= 2:
                        env_key = parts[1]
                raise FleetEnvironmentAccessError(error_message, env_key=env_key)
            else:
                raise FleetPermissionError(error_message)
        elif status_code == 400:
            # Handle 400 errors - bad requests, region errors, environment/version not found
            if "region" in error_message.lower() and (
                "not supported" in error_message.lower()
                or "unsupported" in error_message.lower()
            ):
                # Extract region and supported regions if possible
                region = None
                supported_regions = []
                if "Region" in error_message:
                    # Try to extract region from "Region X not supported"
                    try:
                        parts = error_message.split("Region ")[1].split(
                            " not supported"
                        )
                        if parts:
                            region = parts[0]
                    except (IndexError, ValueError):
                        pass
                    # Try to extract supported regions from "Please use [...]"
                    if "Please use" in error_message and "[" in error_message:
                        try:
                            regions_str = error_message.split("[")[1].split("]")[0]
                            supported_regions = [
                                r.strip().strip("'\"") for r in regions_str.split(",")
                            ]
                        except (IndexError, ValueError):
                            pass
                raise FleetRegionError(
                    error_message, region=region, supported_regions=supported_regions
                )
            elif (
                "environment" in error_message.lower()
                and "not found" in error_message.lower()
            ):
                # Extract env_key if possible
                env_key = None
                if "'" in error_message:
                    parts = error_message.split("'")
                    if len(parts) >= 2:
                        env_key = parts[1]
                raise FleetEnvironmentNotFoundError(error_message, env_key=env_key)
            elif (
                "version" in error_message.lower()
                and "not found" in error_message.lower()
            ):
                # Extract version and env_key if possible
                version = None
                env_key = None
                if "'" in error_message:
                    parts = error_message.split("'")
                    if len(parts) >= 2:
                        version = parts[1]
                    if len(parts) >= 4:
                        env_key = parts[3]
                raise FleetVersionNotFoundError(
                    error_message, version=version, env_key=env_key
                )
            else:
                raise FleetBadRequestError(error_message)
        elif status_code == 429:
            # Rate limit errors (not instance limit which is now 403)
            raise FleetRateLimitError(error_message)
        else:
            raise FleetAPIError(
                error_message,
                status_code=status_code,
                response_data=error_data if "error_data" in locals() else None,
            )
