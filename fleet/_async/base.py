import httpx
from typing import Dict, Any, Optional
import json
import logging

from ..models import InstanceResponse
from ..config import GLOBAL_BASE_URL
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
        import time
        import asyncio
        import ssl
        import socket
        from urllib.parse import urlparse
        
        base_url = base_url or self.base_url
        full_url = f"{base_url}{url}"
        
        # Parse URL for detailed logging
        parsed_url = urlparse(full_url)
        
        # Log comprehensive request details
        logger.debug(f"=== Starting {method} request ===")
        logger.debug(f"Full URL: {full_url}")
        logger.debug(f"Host: {parsed_url.hostname}, Port: {parsed_url.port or (443 if parsed_url.scheme == 'https' else 80)}")
        logger.debug(f"Path: {parsed_url.path}")
        logger.debug(f"Query: {parsed_url.query}")
        
        if params:
            logger.debug(f"URL params: {params}")
        if json:
            # Log a truncated version of the JSON for security
            json_summary = {k: f"<{type(v).__name__}>" if k in ['bundle', 'bundle_data'] 
                          else (v if len(str(v)) < 100 else f"{str(v)[:100]}...") 
                          for k, v in (json.items() if isinstance(json, dict) else {"payload": json})}
            logger.debug(f"Request JSON summary: {json_summary}")
            
        # Log additional request kwargs
        if kwargs:
            safe_kwargs = {k: v for k, v in kwargs.items() if k not in ['headers']}  # Headers logged separately
            logger.debug(f"Additional request kwargs: {safe_kwargs}")
            
        # Log httpx client configuration
        client_info = {
            'timeout': str(self.httpx_client.timeout),
            'limits': str(self.httpx_client.limits),
            'proxies': bool(self.httpx_client._mounts),  # Check if proxies configured
            'verify_ssl': getattr(self.httpx_client, '_verify', True),
        }
        logger.debug(f"HTTP client config: {client_info}")
        
        # Pre-request timing and network checks
        start_time = time.time()
        dns_start = time.time()
        
        try:
            # DNS resolution timing (if not cached)
            try:
                import socket
                host_ip = socket.gethostbyname(parsed_url.hostname)
                dns_duration = time.time() - dns_start
                logger.debug(f"DNS resolution: {parsed_url.hostname} -> {host_ip} ({dns_duration:.3f}s)")
            except Exception as dns_error:
                dns_duration = time.time() - dns_start
                logger.warning(f"DNS resolution failed after {dns_duration:.3f}s: {dns_error}")
            
            # Log headers being sent
            headers = self.get_headers()
            safe_headers = {k: v if k.lower() != 'authorization' else f"Bearer {v[-8:]}" 
                          for k, v in headers.items()}
            logger.debug(f"Request headers: {safe_headers}")
            
            # Additional pre-request debugging
            logger.debug("Checking httpx client status...")
            logger.debug(f"Client is closed: {self.httpx_client.is_closed}")
            
            # Test connectivity with a simple check
            logger.debug("About to initiate HTTP request...")
            logger.debug(f"Request method: {method}")
            logger.debug(f"Request URL: {full_url}")
            logger.debug(f"Request params: {params}")
            if json:
                logger.debug(f"Request JSON size: {len(str(json))} chars")
            
            # Make the actual request with detailed timing
            logger.debug("=== STARTING HTTP REQUEST EXECUTION ===")
            request_start = time.time()
            
            # Log every 5 seconds if request is taking too long
            async def log_progress():
                elapsed = 0
                while True:
                    await asyncio.sleep(5)
                    elapsed += 5
                    if hasattr(log_progress, 'stop'):
                        break
                    logger.warning(f"HTTP request still in progress after {elapsed}s...")
            
            progress_task = asyncio.create_task(log_progress())
            
            try:
                logger.debug(f"Calling httpx_client.request() with timeout: {self.httpx_client.timeout}")
                response = await self.httpx_client.request(
                    method,
                    full_url,
                    headers=headers,
                    params=params,
                    json=json,
                    **kwargs,
                )
                log_progress.stop = True  # Stop the progress logging
                progress_task.cancel()
            except Exception as e:
                log_progress.stop = True  # Stop the progress logging
                progress_task.cancel()
                raise
            
            request_duration = time.time() - request_start
            total_duration = time.time() - start_time
            
            logger.debug(f"HTTP request completed in {request_duration:.3f}s (total: {total_duration:.3f}s)")
            logger.debug(f"Response status: {response.status_code} {response.reason_phrase}")
            
            # Log response headers and metadata
            response_headers = dict(response.headers)
            important_headers = {
                'content-type': response_headers.get('content-type', 'unknown'),
                'content-length': response_headers.get('content-length', 'unknown'),
                'server': response_headers.get('server', 'unknown'),
                'x-request-id': response_headers.get('x-request-id', 'none'),
                'cache-control': response_headers.get('cache-control', 'none'),
                'connection': response_headers.get('connection', 'unknown'),
            }
            logger.debug(f"Response headers: {important_headers}")
            
            # Log HTTP version and connection info
            logger.debug(f"HTTP version: {response.http_version}")
            logger.debug(f"Response encoding: {response.encoding}")
            
            # Network timing breakdown (if available)
            if hasattr(response, 'elapsed'):
                logger.debug(f"Response elapsed time: {response.elapsed}")
            
            # Log response size and content info
            try:
                content_peek = response.content[:200] if len(response.content) <= 200 else response.content[:200] + b'...'
                logger.debug(f"Response content preview ({len(response.content)} bytes): {content_peek}")
            except Exception as content_error:
                logger.debug(f"Could not preview response content: {content_error}")
            
            # Log response text for errors or debug mode (with size limits)
            if response.status_code >= 400 or logger.isEnabledFor(10):  # 10 = DEBUG level
                try:
                    response_text = response.text
                    if len(response_text) > 2000:
                        logger.debug(f"Response text (first 1000 chars): {response_text[:1000]}")
                        logger.debug(f"Response text (last 1000 chars): {response_text[-1000:]}")
                        logger.debug(f"... ({len(response_text) - 2000} chars omitted) ...")
                    else:
                        logger.debug(f"Full response text: {response_text}")
                except Exception as text_error:
                    logger.debug(f"Could not read response text: {text_error}")

            # Check for HTTP errors
            if response.status_code >= 400:
                logger.warning(f"HTTP {response.status_code} error from {method} {full_url}")
                self._handle_error_response(response)
            else:
                logger.debug(f"=== {method} request successful ===")

            return response
            
        except httpx.TimeoutException as e:
            duration = time.time() - start_time
            logger.error(f"=== REQUEST TIMEOUT ===")
            logger.error(f"Request to {full_url} timed out after {duration:.3f}s")
            logger.error(f"Timeout type: {type(e).__name__}")
            logger.error(f"Timeout details: {str(e)}")
            logger.error(f"Client timeout config: {self.httpx_client.timeout}")
            raise FleetTimeoutError(f"Request timed out after {duration:.3f}s: {str(e)}")
            
        except httpx.ConnectError as e:
            duration = time.time() - start_time
            logger.error(f"=== CONNECTION ERROR ===")
            logger.error(f"Failed to connect to {full_url} after {duration:.3f}s")
            logger.error(f"Connection error: {str(e)}")
            logger.error(f"Host: {parsed_url.hostname}:{parsed_url.port or (443 if parsed_url.scheme == 'https' else 80)}")
            raise FleetAPIError(f"Connection failed: {str(e)}")
            
        except httpx.HTTPStatusError as e:
            duration = time.time() - start_time
            logger.error(f"=== HTTP STATUS ERROR ===")
            logger.error(f"HTTP error {e.response.status_code} from {full_url} after {duration:.3f}s")
            logger.error(f"Error details: {str(e)}")
            raise FleetAPIError(f"HTTP error {e.response.status_code}: {str(e)}")
            
        except httpx.RequestError as e:
            duration = time.time() - start_time
            logger.error(f"=== GENERAL REQUEST ERROR ===")
            logger.error(f"Request to {full_url} failed after {duration:.3f}s")
            logger.error(f"Error type: {type(e).__name__}")
            logger.error(f"Error details: {str(e)}")
            
            # Try to extract more details from the error
            if hasattr(e, '__cause__') and e.__cause__:
                logger.error(f"Underlying cause: {type(e.__cause__).__name__}: {e.__cause__}")
                
            raise FleetAPIError(f"Request failed: {str(e)}")
            
        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"=== UNEXPECTED ERROR ===")
            logger.error(f"Unexpected error during request to {full_url} after {duration:.3f}s")
            logger.error(f"Error type: {type(e).__name__}")
            logger.error(f"Error details: {str(e)}")
            logger.error(f"Full traceback:", exc_info=True)
            raise FleetAPIError(f"Unexpected error: {str(e)}")

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
