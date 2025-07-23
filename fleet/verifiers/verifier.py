"""Fleet SDK Verifier - Async Version.

Provides a @verifier decorator that can wrap any sync function to support
both local execution and remote execution via .remote() method.

The decorated function must take 'env' as its first parameter, making it explicit
that verifiers operate within an environment context.
"""

import functools
import uuid
import logging
import hashlib
from typing import Any, Callable, Dict, Optional, List, TypeVar, Set

from .bundler import FunctionBundler
from ..client import Environment

logger = logging.getLogger(__name__)

F = TypeVar('F', bound=Callable[..., Any])

# Global cache to track which bundle SHAs have been uploaded to S3
_uploaded_bundle_shas: Set[str] = set()


@functools.lru_cache(maxsize=128)
def _get_bundle_sha(bundle_data: bytes) -> str:
    """Calculate SHA256 hash of bundle data with LRU caching."""
    return hashlib.sha256(bundle_data).hexdigest()


class SyncVerifierFunction:
    """Wrapper for a verified function that supports local execution with env-first pattern."""
    
    def __init__(
        self,
        func: F,
        key: str,
        extra_requirements: Optional[List[str]] = None,
        verifier_id: Optional[str] = None
    ):
        self.func = func
        self.key = key
        self.name = key  # Keep name for backward compatibility
        self.verifier_id = verifier_id or str(uuid.uuid4())
        self.extra_requirements = extra_requirements or []
        self._bundler = FunctionBundler()
        self._bundle_sha: Optional[str] = None  # Cached bundle SHA
        self._bundle_data: Optional[bytes] = None  # Cached bundle data
        
        # Copy function metadata
        functools.update_wrapper(self, func)
    
    def _get_or_create_bundle(self) -> tuple[bytes, str]:
        """Get or create bundle data and return (bundle_data, sha)."""
        if self._bundle_data is None or self._bundle_sha is None:
            # Create bundle and cache it
            self._bundle_data = self._bundler.create_bundle(
                self.func, 
                self.extra_requirements,
                self.verifier_id
            )
            self._bundle_sha = _get_bundle_sha(self._bundle_data)
            logger.debug(f"Created bundle for {self.name} with SHA: {self._bundle_sha}")
        
        return self._bundle_data, self._bundle_sha
    
    def _check_bundle_status(self, env: Environment) -> tuple[str, bool]:
        """Check if bundle needs to be uploaded and return (sha, needs_upload)."""
        bundle_data, bundle_sha = self._get_or_create_bundle()
        
        # 1. Check local process cache first
        if bundle_sha in _uploaded_bundle_shas:
            logger.debug(f"Bundle {bundle_sha[:8]}... found in local cache")
            return bundle_sha, False  # Already uploaded, no upload needed
        
        # 2. Check if bundle exists on server (pseudocode)
        # TODO: Add endpoint to check if bundle SHA exists in S3
        try:
            exists = env.check_bundle_exists(bundle_sha)
            if exists.success:
                logger.info(f"Bundle {bundle_sha[:8]}... found on server, updating cache")
                _uploaded_bundle_shas.add(bundle_sha)
                return bundle_sha, False  # Found on server, no upload needed
        except Exception as e:
            logger.warning(f"Failed to check bundle existence: {e}")
        
        # 3. Bundle not found locally or on server - upload needed
        logger.info(f"Bundle {bundle_sha[:8]}... needs to be uploaded")
        return bundle_sha, True  # Upload needed
    
    def __call__(self, env: Environment, *args, **kwargs) -> float:
        """Local execution of the verifier function with env as first parameter."""
        try:
            result = self.func(env, *args, **kwargs)
            
            # Handle different return types
            if isinstance(result, (int, float)):
                # Direct score return
                return float(result)
            elif isinstance(result, dict) and "score" in result:
                # For local execution, return the full dict if that's what the function returns
                return result
            else:
                # Try to extract score from object attributes
                if hasattr(result, 'score'):
                    return float(result.score)
                else:
                    raise ValueError(f"Verifier function must return a score (number). Got {type(result)}")
                    
        except Exception as e:
            logger.error(f"Error in verifier {self.name}: {e}")
            # Return error score 0
            return 0.0
    
    def remote(self, env: Environment, *args, **kwargs) -> float:
        """Remote execution of the verifier function with SHA-based bundle caching."""
        try:
            # Check if bundle needs to be uploaded
            bundle_sha, needs_upload = self._check_bundle_status(env)
            
            if needs_upload:
                # Need to upload bundle to S3
                logger.info(f"Uploading bundle {bundle_sha[:8]}... for {self.key}")
                bundle_data, _ = self._get_or_create_bundle()
                
                response = env.execute_verifier_remote(
                    bundle_data=bundle_data,
                    bundle_sha=bundle_sha,
                    key=self.key,
                    function_name=self.func.__name__,
                    args=args,
                    kwargs=kwargs,
                    needs_upload=True
                )
                
                # Mark as uploaded after successful execution
                _uploaded_bundle_shas.add(bundle_sha)
                logger.debug(f"Registered bundle {bundle_sha[:8]}... as uploaded")
                
            else:
                # Bundle already available - execute without upload
                logger.info(f"Executing cached bundle {bundle_sha[:8]}... for {self.key}")
                bundle_data, _ = self._get_or_create_bundle()
                
                response = env.execute_verifier_remote(
                    bundle_data=bundle_data,  # Still need bundle_data for local caching
                    bundle_sha=bundle_sha,
                    key=self.key,
                    function_name=self.func.__name__,
                    args=args,
                    kwargs=kwargs,
                    needs_upload=False  # Don't upload, just execute
                )
            
            # Handle response
            if response.success:
                return self._process_result(response.result)
            else:
                self._raise_remote_error(response.error)
                
        except Exception as e:
            logger.error(f"Remote execution failed for {self.key}: {e}")
            # If it's an HTTP error, try to get more details
            if hasattr(e, 'response') and hasattr(e.response, 'text'):
                logger.error(f"Server response: {e.response.text}")
            raise
    
    def _process_result(self, result: Any) -> float:
        """Process remote execution result, handling different return types."""
        # Handle different return types like local execution
        if isinstance(result, (int, float)):
            return float(result)
        elif isinstance(result, dict) and "score" in result:
            return float(result["score"])
        else:
            # Try to extract score from object attributes
            if hasattr(result, 'score'):
                return float(result.score)
            else:
                # Best effort conversion
                try:
                    return float(result)
                except (ValueError, TypeError):
                    logger.warning(f"Could not convert result to float: {result}")
                    return 0.0
    
    def _raise_remote_error(self, error_info: Dict[str, Any]):
        """Reconstruct remote error as local exception."""
        error_type = error_info.get("type", "RuntimeError")
        message = error_info.get("message", "Remote execution failed")
        traceback_str = error_info.get("traceback", "")
        
        # Create a rich error message
        full_message = f"""
Remote verifier execution failed:
{message}

Remote traceback:
{traceback_str}
        """.strip()
        
        # Try to raise the original exception type
        try:
            exception_class = getattr(__builtins__, error_type, RuntimeError)
            raise exception_class(full_message)
        except:
            raise RuntimeError(full_message)
    
    def _get_env_id(self, env: Environment) -> str:
        """Generate a unique identifier for the environment."""
        # Use instance base URL or similar unique identifier
        if hasattr(env, 'instance') and hasattr(env.instance, 'base_url'):
            return f"{env.instance.base_url}"
        else:
            # Fallback to object id (less ideal but works)
            return str(id(env))
    
    def _is_bundle_not_found_error(self, error: Exception) -> bool:
        """Check if the error indicates the bundle was not found on the server."""
        # Check for common "bundle not found" error patterns
        error_msg = str(error).lower()
        return (
            "bundle not found" in error_msg or
            "verifier not found" in error_msg or
            "404" in error_msg or
            "not found" in error_msg
        )


def verifier(
    key: Optional[str] = None,
    extra_requirements: Optional[List[str]] = None
) -> Callable[[F], SyncVerifierFunction]:
    """
    Decorator to create a verifier function with env-first pattern.
    
    The decorated function must take 'env' as its first parameter, making it explicit
    that verifiers operate within an environment context. This makes verifiers reusable
    across different environments.
    
    Args:
        key: Optional key for the verifier. Defaults to function name.
        extra_requirements: Additional PyPI packages needed by the verifier.
    
    Example:
        @verifier(
            key="test_database_state",
            extra_requirements=["torch==2.3.0"]
        )
        def check_user_count(env, expected_count: int) -> float:
            db = env.db()
            result = db.query("SELECT COUNT(*) FROM users")
            actual_count = result.rows[0][0]
            return 1.0 if actual_count >= expected_count else 0.0
        
        # Usage with different environments
        env1 = flt.env.make("fira")
        env2 = flt.env.make("another_env")
        
        # Local execution
        result = await check_user_count(env1, 5)
        result = await check_user_count(env2, 5)  # Same verifier, different env
        
        # Remote execution
        result = await check_user_count.remote(env1, 5)
    """
    def decorator(func: F) -> SyncVerifierFunction:
        verifier_key = key or func.__name__
        verifier_uuid = str(uuid.uuid4())
        
        return SyncVerifierFunction(
            func,
            verifier_key,
            extra_requirements,
            verifier_uuid
        )
    
    return decorator