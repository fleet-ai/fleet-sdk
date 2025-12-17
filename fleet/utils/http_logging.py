"""HTTP traffic logging via httpx event hooks.

Captures request/response pairs and writes to JSONL file.
Works with any httpx-based client (including google-genai).
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
import threading

# Sensitive headers to redact
SENSITIVE_HEADERS = {
    "authorization", "x-api-key", "api-key", "x-goog-api-key",
    "x-gemini-api-key", "x-openai-api-key", "x-anthropic-api-key",
    "cookie", "set-cookie", "x-auth-token", "x-access-token",
}


def _redact_headers(headers: dict) -> dict:
    """Redact sensitive headers."""
    redacted = {}
    for k, v in headers.items():
        if k.lower() in SENSITIVE_HEADERS:
            if len(str(v)) > 12:
                redacted[k] = str(v)[:8] + "...[REDACTED]"
            else:
                redacted[k] = "[REDACTED]"
        else:
            redacted[k] = str(v)
    return redacted


class HttpTrafficLogger:
    """Logs HTTP traffic to JSONL file."""
    
    _instance: Optional["HttpTrafficLogger"] = None
    _lock = threading.Lock()
    
    def __init__(self, log_file: Optional[Path] = None):
        if log_file is None:
            log_dir = Path.home() / ".fleet" / "proxy_logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / f"traffic_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
        
        self.log_file = log_file
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(log_file, "a")
        self._write_lock = threading.Lock()
        self._request_times: dict = {}  # Track request start times
    
    @classmethod
    def get(cls, log_file: Optional[Path] = None) -> "HttpTrafficLogger":
        """Get singleton instance."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls(log_file)
            return cls._instance
    
    @classmethod
    def set_log_file(cls, log_file: Path):
        """Set log file for singleton (creates new instance if needed)."""
        with cls._lock:
            if cls._instance is not None:
                cls._instance.close()
            cls._instance = cls(log_file)
        return cls._instance
    
    def log_request(self, request) -> str:
        """Log request, return request ID for matching response."""
        request_id = f"{id(request)}_{time.time()}"
        self._request_times[request_id] = time.time()
        return request_id
    
    def log_response(self, request, response, request_id: Optional[str] = None):
        """Log complete request/response pair."""
        start_time = self._request_times.pop(request_id, None) if request_id else None
        duration_ms = int((time.time() - start_time) * 1000) if start_time else None
        
        # Extract host
        host = str(request.url.host) if hasattr(request.url, 'host') else str(request.url).split('/')[2]
        
        # Build request entry
        request_headers = dict(request.headers) if hasattr(request, 'headers') else {}
        request_body = None
        if hasattr(request, 'content') and request.content:
            try:
                body_bytes = request.content if isinstance(request.content, bytes) else bytes(request.content)
                if len(body_bytes) < 50000:
                    request_body = body_bytes.decode('utf-8', errors='replace')
            except:
                pass
        
        # Build response entry  
        response_headers = dict(response.headers) if hasattr(response, 'headers') else {}
        response_body = None
        if hasattr(response, 'content') and response.content:
            try:
                if len(response.content) < 50000:
                    response_body = response.content.decode('utf-8', errors='replace')
            except:
                pass
        
        entry = {
            "type": "http",
            "timestamp": datetime.now().isoformat(),
            "host": host,
            "duration_ms": duration_ms,
            "logged_at": datetime.now().isoformat(),
            "request": {
                "method": str(request.method),
                "url": str(request.url),
                "headers": _redact_headers(request_headers),
                "body": request_body,
                "body_length": len(request.content) if hasattr(request, 'content') and request.content else 0,
            },
            "response": {
                "status_code": response.status_code,
                "headers": _redact_headers(response_headers),
                "body": response_body,
                "body_length": len(response.content) if hasattr(response, 'content') and response.content else 0,
            },
        }
        
        with self._write_lock:
            self._file.write(json.dumps(entry) + "\n")
            self._file.flush()
    
    def close(self):
        """Close the log file."""
        with self._write_lock:
            if self._file:
                self._file.close()
                self._file = None


def install_httpx_hooks():
    """Install global httpx event hooks for traffic logging.
    
    This patches httpx to log all HTTP traffic automatically.
    """
    try:
        import httpx
    except ImportError:
        return
    
    logger = HttpTrafficLogger.get()
    original_send = httpx.Client.send
    original_async_send = httpx.AsyncClient.send
    
    def patched_send(self, request, **kwargs):
        request_id = logger.log_request(request)
        response = original_send(self, request, **kwargs)
        logger.log_response(request, response, request_id)
        return response
    
    async def patched_async_send(self, request, **kwargs):
        request_id = logger.log_request(request)
        response = await original_async_send(self, request, **kwargs)
        logger.log_response(request, response, request_id)
        return response
    
    httpx.Client.send = patched_send
    httpx.AsyncClient.send = patched_async_send


def setup_logging(log_file: Optional[Path] = None):
    """Setup HTTP traffic logging.
    
    Args:
        log_file: Path to JSONL log file. If None, creates timestamped file in ~/.fleet/proxy_logs/
    """
    if log_file:
        HttpTrafficLogger.set_log_file(log_file)
    install_httpx_hooks()
