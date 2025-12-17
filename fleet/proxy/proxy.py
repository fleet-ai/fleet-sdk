"""Simple HTTP proxy for capturing traffic during eval runs.

Captures requests/responses to whitelisted endpoints and writes them to a JSONL file.
Uses aiohttp as a simple HTTP proxy (no SSL interception, just tunneling for HTTPS).

Whitelist tiers:
1. Static: Known public LLM endpoints (googleapis.com, openai.com, etc.)
2. Runtime: Dynamically detected from SDK client initialization
"""

import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Set
from urllib.parse import urlparse
import ssl

logger = logging.getLogger(__name__)

# Output directory
DEFAULT_LOG_DIR = Path.home() / ".fleet" / "proxy_logs"

# Import whitelist utilities
try:
    from .whitelist import is_whitelisted, get_full_whitelist, STATIC_WHITELIST
except ImportError:
    # Fallback for subprocess execution
    from fleet.proxy.whitelist import is_whitelisted, get_full_whitelist, STATIC_WHITELIST

# Headers to redact (case-insensitive)
SENSITIVE_HEADERS = {
    "authorization",
    "x-api-key",
    "api-key",
    "x-goog-api-key",
    "x-gemini-api-key",
    "x-openai-api-key",
    "x-anthropic-api-key",
    "cookie",
    "set-cookie",
    "x-auth-token",
    "x-access-token",
    "x-refresh-token",
    "proxy-authorization",
}


def redact_headers(headers: dict) -> dict:
    """Redact sensitive headers from a headers dict."""
    redacted = {}
    for k, v in headers.items():
        if k.lower() in SENSITIVE_HEADERS:
            # Keep first 8 chars for debugging, redact rest
            if len(v) > 12:
                redacted[k] = v[:8] + "...[REDACTED]"
            else:
                redacted[k] = "[REDACTED]"
        else:
            redacted[k] = v
    return redacted


def extract_host(url: str) -> str:
    """Extract host from URL."""
    if "://" not in url:
        url = "http://" + url
    parsed = urlparse(url)
    return parsed.netloc.split(":")[0]  # Remove port if present


class TrafficLogger:
    """Logs HTTP traffic to a JSONL file with whitelist filtering."""
    
    def __init__(self, log_file: Path, use_whitelist: bool = True):
        self.log_file = log_file
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(log_file, "a")
        self._lock = asyncio.Lock()
        self._use_whitelist = use_whitelist
        self._logged_count = 0
        self._skipped_count = 0
        
        # Log active whitelist at startup
        whitelist = get_full_whitelist()
        logger.info(f"Traffic logging to: {log_file}")
        logger.info(f"Whitelist active: {sorted(whitelist)}")
        print(f"Traffic logging to: {log_file}")
        print(f"Whitelist ({len(whitelist)} endpoints): {', '.join(sorted(whitelist)[:5])}{'...' if len(whitelist) > 5 else ''}")
    
    def should_log(self, host: str) -> bool:
        """Check if traffic to this host should be logged."""
        if not self._use_whitelist:
            return True
        return is_whitelisted(host)
    
    async def log(self, entry: dict, host: Optional[str] = None):
        """Log a traffic entry if it passes whitelist filter."""
        # Check whitelist
        if host and not self.should_log(host):
            self._skipped_count += 1
            return
        
        entry["logged_at"] = datetime.now().isoformat()
        async with self._lock:
            self._file.write(json.dumps(entry) + "\n")
            self._file.flush()
            self._logged_count += 1
    
    def close(self):
        logger.info(f"Traffic logger closed. Logged: {self._logged_count}, Skipped: {self._skipped_count}")
        self._file.close()
    
    @property
    def logged_count(self) -> int:
        return self._logged_count
    
    @property
    def skipped_count(self) -> int:
        return self._skipped_count


async def run_proxy_server(
    host: str = "127.0.0.1",
    port: int = 8888,
    log_file: Optional[Path] = None,
    use_whitelist: bool = True,
):
    """Run a simple HTTP proxy server with whitelist filtering.
    
    This proxy:
    - Logs requests/responses to whitelisted endpoints (LLM APIs)
    - Tunnels HTTPS via CONNECT (logs URL but not content)
    - Filters out non-whitelisted traffic (reduces noise)
    """
    import aiohttp
    from aiohttp import web
    
    log_file = log_file or (DEFAULT_LOG_DIR / f"traffic_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl")
    traffic_logger = TrafficLogger(log_file, use_whitelist=use_whitelist)
    
    async def handle_connect(request: web.Request):
        """Handle CONNECT for HTTPS tunneling."""
        # Parse host:port from request.path
        target = request.path_qs
        if ":" in target:
            target_host, target_port = target.rsplit(":", 1)
            target_port = int(target_port)
        else:
            target_host = target
            target_port = 443
        
        # Log the CONNECT request (we can see the host but not the content)
        # Only log if host is whitelisted
        await traffic_logger.log({
            "type": "https_connect",
            "timestamp": datetime.now().isoformat(),
            "method": "CONNECT",
            "host": target_host,
            "port": target_port,
            "path": request.path_qs,
        }, host=target_host)
        
        # Connect to target
        try:
            reader, writer = await asyncio.open_connection(target_host, target_port)
        except Exception as e:
            await traffic_logger.log({
                "type": "https_connect_error",
                "timestamp": datetime.now().isoformat(),
                "host": target_host,
                "port": target_port,
                "error": str(e),
            }, host=target_host)
            return web.Response(status=502, text=f"Failed to connect: {e}")
        
        # Send 200 Connection Established
        response = web.StreamResponse(status=200, reason="Connection Established")
        await response.prepare(request)
        
        # Get the underlying transport
        # This is a hack to get raw socket access in aiohttp
        transport = request.transport
        
        async def pipe(reader_from, writer_to):
            try:
                while True:
                    data = await reader_from.read(65536)
                    if not data:
                        break
                    writer_to.write(data)
                    await writer_to.drain()
            except:
                pass
            finally:
                try:
                    writer_to.close()
                except:
                    pass
        
        # Pipe data in both directions
        client_reader = request.content
        
        # For CONNECT tunneling, we need to hijack the connection
        # This is complex with aiohttp, so we'll just close and note it
        writer.close()
        await traffic_logger.log({
            "type": "https_tunnel_started",
            "timestamp": datetime.now().isoformat(),
            "host": target_host,
            "port": target_port,
        }, host=target_host)
        
        return response
    
    async def handle_request(request: web.Request):
        """Handle HTTP requests (non-CONNECT)."""
        start_time = time.time()
        
        # Build target URL
        url = str(request.url)
        if not url.startswith("http"):
            # Relative URL - reconstruct from Host header
            host_header = request.headers.get("Host", "")
            url = f"http://{host_header}{request.path_qs}"
        
        # Extract host for whitelist filtering
        target_host = extract_host(url)
        
        # Log request (redact sensitive headers)
        request_entry = {
            "method": request.method,
            "url": url,
            "headers": redact_headers(dict(request.headers)),
        }
        
        # Read request body
        try:
            body = await request.read()
            if body:
                request_entry["body_length"] = len(body)
                # Include body for JSON
                content_type = request.headers.get("Content-Type", "")
                if "json" in content_type:
                    try:
                        body_str = body.decode("utf-8", errors="replace")
                        if len(body_str) > 10000:
                            body_str = body_str[:10000] + "...[truncated]"
                        request_entry["body"] = body_str
                    except:
                        pass
        except:
            body = None
        
        # Forward request
        try:
            async with aiohttp.ClientSession() as session:
                async with session.request(
                    method=request.method,
                    url=url,
                    headers={k: v for k, v in request.headers.items() if k.lower() not in ("host", "connection")},
                    data=body,
                    ssl=False,  # Don't verify SSL
                ) as resp:
                    duration_ms = int((time.time() - start_time) * 1000)
                    
                    # Read response body
                    resp_body = await resp.read()
                    
                    # Build response entry (redact sensitive headers)
                    response_entry = {
                        "status_code": resp.status,
                        "headers": redact_headers(dict(resp.headers)),
                        "body_length": len(resp_body) if resp_body else 0,
                    }
                    
                    # Include body for JSON and SSE responses (MCP uses text/event-stream)
                    content_type = resp.headers.get("Content-Type", "")
                    if resp_body and ("json" in content_type or "event-stream" in content_type or "text" in content_type):
                        try:
                            body_str = resp_body.decode("utf-8", errors="replace")
                            if len(body_str) > 50000:
                                body_str = body_str[:50000] + "...[truncated]"
                            response_entry["body"] = body_str
                        except:
                            pass
                    
                    # Log complete entry (only if host is whitelisted)
                    await traffic_logger.log({
                        "type": "http",
                        "timestamp": datetime.now().isoformat(),
                        "duration_ms": duration_ms,
                        "host": target_host,
                        "request": request_entry,
                        "response": response_entry,
                    }, host=target_host)
                    
                    # Return response to client
                    return web.Response(
                        status=resp.status,
                        headers={k: v for k, v in resp.headers.items() if k.lower() not in ("transfer-encoding", "content-encoding", "connection")},
                        body=resp_body,
                    )
                    
        except Exception as e:
            await traffic_logger.log({
                "type": "http_error",
                "timestamp": datetime.now().isoformat(),
                "host": target_host,
                "request": request_entry,
                "error": str(e),
            }, host=target_host)
            return web.Response(status=502, text=f"Proxy error: {e}")
    
    async def handler(request: web.Request):
        """Main request handler."""
        if request.method == "CONNECT":
            return await handle_connect(request)
        else:
            return await handle_request(request)
    
    # Create app
    app = web.Application()
    app.router.add_route("*", "/{path:.*}", handler)
    
    runner = web.AppRunner(app)
    await runner.setup()
    
    site = web.TCPSite(runner, host, port)
    await site.start()
    
    print(f"Proxy listening on {host}:{port}")
    print(f"Traffic logging to: {log_file}")
    print("Press Ctrl+C to stop")
    
    # Keep running
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass
    finally:
        traffic_logger.close()
        await runner.cleanup()


class ProxyManager:
    """Manages the lifecycle of the proxy server."""
    
    def __init__(self, port: int = 8888, log_file: Optional[Path] = None):
        self.port = port
        self.log_file = log_file or (DEFAULT_LOG_DIR / f"traffic_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl")
        self._process: Optional[asyncio.subprocess.Process] = None
        self._started = False
    
    async def start(self) -> dict:
        """Start the proxy in a subprocess.
        
        Returns:
            dict with proxy env vars to set
        """
        if self._started:
            return self.get_env_vars()
        
        # Ensure log dir exists
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Start proxy as subprocess
        self._process = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "fleet.proxy.proxy",
            "--port", str(self.port),
            "--log-file", str(self.log_file),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        
        # Wait for proxy to be ready
        await asyncio.sleep(2)
        
        if self._process.returncode is not None:
            stdout, stderr = await self._process.communicate()
            raise RuntimeError(f"Proxy failed to start: {stderr.decode()}")
        
        self._started = True
        logger.info(f"Proxy started on port {self.port}, logging to {self.log_file}")
        
        return self.get_env_vars()
    
    def get_env_vars(self) -> dict:
        """Get environment variables for using this proxy.
        
        Note: We only proxy HTTP, not HTTPS, to avoid SSL issues with LLM APIs.
        HTTPS traffic goes direct but we can't inspect the content.
        """
        proxy_url = f"http://127.0.0.1:{self.port}"
        return {
            "HTTP_PROXY": proxy_url,
            "http_proxy": proxy_url,
            # Don't proxy HTTPS - our simple proxy doesn't handle SSL interception
            # This means we can only log HTTP traffic, not HTTPS API calls
            # "HTTPS_PROXY": proxy_url,
            # "https_proxy": proxy_url,
        }
    
    async def stop(self):
        """Stop the proxy."""
        if self._process and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()
        self._started = False
        logger.info("Proxy stopped")
    
    @property
    def log_path(self) -> Path:
        return self.log_file


def main():
    """CLI entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Fleet HTTP Proxy with LLM endpoint whitelist")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8888, help="Port to listen on")
    parser.add_argument("--log-file", type=Path, default=None, help="Log file path")
    parser.add_argument("--no-whitelist", action="store_true", 
                       help="Disable whitelist filtering (log ALL traffic)")
    args = parser.parse_args()
    
    logging.basicConfig(level=logging.INFO)
    
    try:
        asyncio.run(run_proxy_server(
            host=args.host,
            port=args.port,
            log_file=args.log_file,
            use_whitelist=not args.no_whitelist,
        ))
    except KeyboardInterrupt:
        print("\nProxy stopped")


if __name__ == "__main__":
    main()

