"""
Endpoint whitelist management for proxy capture.

Two-tier whitelist:
1. Static: Known public LLM endpoints (in code)
2. Runtime: Dynamically detected from SDK client initialization
"""

import os
import json
from pathlib import Path
from typing import Set
from urllib.parse import urlparse
import threading

# =============================================================================
# Static Whitelist - Known public LLM endpoints
# =============================================================================

STATIC_WHITELIST: Set[str] = {
    # Google / Gemini
    "generativelanguage.googleapis.com",
    "aiplatform.googleapis.com",
    
    # OpenAI
    "api.openai.com",
    
    # Anthropic
    "api.anthropic.com",
    
    # Azure OpenAI
    "openai.azure.com",
    
    # Cohere
    "api.cohere.ai",
    
    # Together AI
    "api.together.xyz",
    
    # Groq
    "api.groq.com",
    
    # Fireworks
    "api.fireworks.ai",
    
    # Replicate
    "api.replicate.com",
    
    # Mistral
    "api.mistral.ai",
}

# =============================================================================
# Runtime Whitelist - Dynamically detected endpoints
# =============================================================================

_runtime_whitelist: Set[str] = set()
_whitelist_lock = threading.Lock()

# File for persisting runtime whitelist (shared with proxy subprocess)
_RUNTIME_WHITELIST_FILE = Path.home() / ".fleet" / "runtime_whitelist.json"


def _extract_host(url: str) -> str:
    """Extract host from URL."""
    if not url:
        return ""
    # Handle URLs without scheme
    if "://" not in url:
        url = "https://" + url
    parsed = urlparse(url)
    return parsed.netloc or parsed.path.split("/")[0]


def register_endpoint(endpoint: str) -> None:
    """
    Register an endpoint to the runtime whitelist.
    
    Args:
        endpoint: URL or hostname of the endpoint
    """
    host = _extract_host(endpoint)
    if not host:
        return
    
    with _whitelist_lock:
        _runtime_whitelist.add(host)
        _save_runtime_whitelist()


def get_runtime_whitelist() -> Set[str]:
    """Get the current runtime whitelist."""
    with _whitelist_lock:
        return _runtime_whitelist.copy()


def get_full_whitelist() -> Set[str]:
    """Get combined static + runtime whitelist."""
    _load_runtime_whitelist()  # Refresh from file
    with _whitelist_lock:
        return STATIC_WHITELIST | _runtime_whitelist


def _save_runtime_whitelist() -> None:
    """Persist runtime whitelist to file."""
    try:
        _RUNTIME_WHITELIST_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_RUNTIME_WHITELIST_FILE, "w") as f:
            json.dump(list(_runtime_whitelist), f)
    except Exception:
        pass  # Best effort


def _load_runtime_whitelist() -> None:
    """Load runtime whitelist from file."""
    global _runtime_whitelist
    try:
        if _RUNTIME_WHITELIST_FILE.exists():
            with open(_RUNTIME_WHITELIST_FILE, "r") as f:
                data = json.load(f)
                with _whitelist_lock:
                    _runtime_whitelist = set(data)
    except Exception:
        pass  # Best effort


def clear_runtime_whitelist() -> None:
    """Clear the runtime whitelist."""
    global _runtime_whitelist
    with _whitelist_lock:
        _runtime_whitelist.clear()
        try:
            if _RUNTIME_WHITELIST_FILE.exists():
                _RUNTIME_WHITELIST_FILE.unlink()
        except Exception:
            pass


def is_whitelisted(host: str) -> bool:
    """Check if a host is in the whitelist."""
    host = host.lower()
    whitelist = get_full_whitelist()
    
    # Exact match
    if host in whitelist:
        return True
    
    # Subdomain match (e.g., us-central1-aiplatform.googleapis.com)
    for pattern in whitelist:
        if host.endswith("." + pattern) or host.endswith(pattern):
            return True
    
    return False


# =============================================================================
# SDK Hooks - Auto-detect endpoints from client initialization
# =============================================================================

_original_genai_client_init = None


def _hook_genai_client():
    """
    Monkey-patch google.genai.Client to capture endpoint configuration.
    Call this early in your application.
    """
    global _original_genai_client_init
    
    try:
        from google import genai
        from google.genai import Client
        
        if _original_genai_client_init is not None:
            return  # Already hooked
        
        _original_genai_client_init = Client.__init__
        
        def _patched_init(self, *args, **kwargs):
            _original_genai_client_init(self, *args, **kwargs)
            
            # Extract base_url from http_options
            http_options = kwargs.get("http_options")
            if http_options:
                base_url = getattr(http_options, "base_url", None)
                if base_url:
                    register_endpoint(base_url)
                    return
            
            # Default Google endpoint
            register_endpoint("generativelanguage.googleapis.com")
        
        Client.__init__ = _patched_init
        
    except ImportError:
        pass  # google-genai not installed


def _hook_openai_client():
    """Monkey-patch openai.OpenAI to capture endpoint configuration."""
    try:
        import openai
        
        original_init = openai.OpenAI.__init__
        
        def _patched_init(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            base_url = kwargs.get("base_url") or os.getenv("OPENAI_BASE_URL", "api.openai.com")
            register_endpoint(base_url)
        
        openai.OpenAI.__init__ = _patched_init
        
    except (ImportError, AttributeError):
        pass


def _hook_anthropic_client():
    """Monkey-patch anthropic.Anthropic to capture endpoint configuration."""
    try:
        import anthropic
        
        original_init = anthropic.Anthropic.__init__
        
        def _patched_init(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            base_url = kwargs.get("base_url") or os.getenv("ANTHROPIC_BASE_URL", "api.anthropic.com")
            register_endpoint(base_url)
        
        anthropic.Anthropic.__init__ = _patched_init
        
    except (ImportError, AttributeError):
        pass


def install_hooks():
    """Install all SDK hooks. Call this early in your application."""
    _hook_genai_client()
    _hook_openai_client()
    _hook_anthropic_client()


# Auto-load runtime whitelist on import
_load_runtime_whitelist()

