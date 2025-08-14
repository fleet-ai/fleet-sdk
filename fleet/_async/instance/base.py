import httpx
import httpx_retries
from typing import Dict, Any, Optional


def default_httpx_client(max_retries: int, timeout: float) -> httpx.AsyncClient:
    if max_retries <= 0:
        return httpx.AsyncClient(timeout=timeout)

    policy = httpx_retries.Retry(
        total=max_retries,
        status_forcelist=[
            404,
            429,
            500,
            502,
            503,
            504,
        ],
        allowed_methods=["GET", "POST", "PATCH", "DELETE"],
        backoff_factor=0.5,
    )
    retry = httpx_retries.RetryTransport(
        transport=httpx.AsyncHTTPTransport(retries=2), retry=policy
    )
    return httpx.AsyncClient(
        timeout=timeout,
        transport=retry,
    )


class BaseWrapper:
    def __init__(self, *, url: str):
        self.url = url

    def get_headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {
            "X-Fleet-SDK-Language": "Python",
            "X-Fleet-SDK-Version": "1.0.0",
        }
        return headers


class AsyncWrapper(BaseWrapper):
    def __init__(self, *, httpx_client: httpx.AsyncClient, **kwargs):
        super().__init__(**kwargs)
        self.httpx_client = httpx_client

    async def request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
        json: Optional[Any] = None,
        **kwargs,
    ) -> httpx.Response:
        import time
        import logging
        
        logger = logging.getLogger(__name__)
        full_url = f"{self.url}{path}"
        
        # Log request details
        logger.debug(f"Instance client making {method} request to {full_url}")
        if params:
            logger.debug(f"Request params: {params}")
        if json:
            # Log a truncated version of the JSON for security
            json_summary = {k: f"<{type(v).__name__}>" if k in ['bundle', 'bundle_data'] 
                          else (v if len(str(v)) < 100 else f"{str(v)[:100]}...") 
                          for k, v in (json.items() if isinstance(json, dict) else {"payload": json})}
            logger.debug(f"Request JSON summary: {json_summary}")
            
        start_time = time.time()
        
        try:
            response = await self.httpx_client.request(
                method,
                full_url,
                headers=self.get_headers(),
                params=params,
                json=json,
                **kwargs,
            )
            
            duration = time.time() - start_time
            logger.debug(f"Instance request to {full_url} completed in {duration:.2f}s with status {response.status_code}")
            
            # Log response details for debugging
            content_type = response.headers.get("content-type", "")
            content_length = response.headers.get("content-length", "unknown")
            logger.debug(f"Instance response: content-type={content_type}, content-length={content_length}")
            
            # Log response text for errors or debug mode
            if response.status_code >= 400 or logger.isEnabledFor(10):  # 10 = DEBUG level
                try:
                    response_text = response.text
                    if len(response_text) > 1000:
                        logger.debug(f"Instance response text (truncated): {response_text[:1000]}...")
                    else:
                        logger.debug(f"Instance response text: {response_text}")
                except Exception as e:
                    logger.debug(f"Could not read instance response text: {e}")
                    
            if response.status_code >= 400:
                logger.warning(f"Instance HTTP {response.status_code} error from {method} {full_url}")
                
            return response
            
        except httpx.TimeoutException as e:
            duration = time.time() - start_time
            logger.error(f"Instance request to {full_url} timed out after {duration:.2f}s: {str(e)}")
            raise
        except httpx.RequestError as e:
            duration = time.time() - start_time
            logger.error(f"Instance request to {full_url} failed after {duration:.2f}s: {str(e)}")
            raise
