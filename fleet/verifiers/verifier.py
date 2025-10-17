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
import inspect
from typing import (
    Any,
    Callable,
    Dict,
    Optional,
    List,
    TypeVar,
    TYPE_CHECKING,
    Tuple,
)

from .bundler import FunctionBundler

if TYPE_CHECKING:
    from ..client import SyncEnv
    from ..models import VerifiersExecuteResponse

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

# Removed global cache - always check server for bundle status


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
        verifier_id: Optional[str] = None,
        sha256: Optional[str] = None,
        raw_code: Optional[str] = None,
    ):
        self.func = func
        self.key = key
        self.verifier_id = verifier_id or str(uuid.uuid4())
        self.extra_requirements = extra_requirements or []
        self._bundler = FunctionBundler()
        self._bundle_sha: Optional[str] = sha256  # Use provided SHA if available
        self._bundle_data: Optional[bytes] = None  # Cached bundle data
        self._raw_code: Optional[str] = raw_code  # Store raw code if provided
        self._is_async = inspect.iscoroutinefunction(func)

        # Copy function metadata
        functools.update_wrapper(self, func)

    def _get_or_create_bundle(self) -> Tuple[bytes, str]:
        """Get or create bundle data and return (bundle_data, sha)."""
        if self._bundle_data is None or self._bundle_sha is None:
            # If we have raw code, create a bundle from it
            if self._raw_code:
                import io
                import zipfile

                # Create zip bundle directly (matching bundler format)
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                    # Add requirements.txt
                    requirements = self.extra_requirements or []
                    if "fleet-python" not in requirements:
                        requirements.append("fleet-python")
                    req_content = "\n".join(requirements)
                    zf.writestr("requirements.txt", req_content)

                    # Add verifier.py with the raw code
                    zf.writestr("verifier.py", self._raw_code)

                self._bundle_data = zip_buffer.getvalue()
                self._bundle_sha = _get_bundle_sha(self._bundle_data)
                logger.debug(
                    f"Created bundle from raw code for {self.key} with SHA: {self._bundle_sha}"
                )
            else:
                # Try to create bundle from function source
                try:
                    self._bundle_data = self._bundler.create_bundle(
                        self.func, self.extra_requirements, self.verifier_id
                    )
                    self._bundle_sha = _get_bundle_sha(self._bundle_data)
                    logger.debug(
                        f"Created bundle for {self.key} with SHA: {self._bundle_sha}"
                    )
                except OSError as e:
                    # Can't create bundle - no source and no raw code
                    raise OSError(f"Cannot create bundle for {self.key}: {e}")

        return self._bundle_data, self._bundle_sha

    def _check_bundle_status(self, env: "SyncEnv") -> Tuple[str, bool]:
        """Check if bundle needs to be uploaded and return (sha, needs_upload)."""
        bundle_data, bundle_sha = self._get_or_create_bundle()

        # If bundle_data is empty, we're using server-side bundle
        if not bundle_data:
            logger.debug(f"Using server-side bundle {bundle_sha[:8]}...")
            return bundle_sha, False  # No upload needed, server has it

        # Always check if bundle exists on server
        try:
            exists = env.check_bundle_exists(bundle_sha)
            if exists.success:
                logger.info(f"Bundle {bundle_sha[:8]}... found on server")
                return bundle_sha, False  # Found on server, no upload needed
        except Exception as e:
            logger.warning(f"Failed to check bundle existence: {e}")

        # Bundle not found on server - upload needed
        logger.info(f"Bundle {bundle_sha[:8]}... needs to be uploaded")
        return bundle_sha, True  # Upload needed

    def __call__(self, env: "SyncEnv", *args, **kwargs) -> float:
        """Local execution of the verifier function with env as first parameter."""
        try:
            if self._is_async:
                # For async functions, await the result
                result = self.func(env, *args, **kwargs)
            else:
                # For sync functions, call directly
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
                if hasattr(result, "score"):
                    return float(result.score)
                else:
                    raise ValueError(
                        f"Verifier function must return a score (number). Got {type(result)}"
                    )

        except Exception as e:
            logger.error(f"Error in verifier {self.key}: {e}")
            # Return error score 0
            return 0.0

    def remote(self, env: "SyncEnv", *args, **kwargs) -> float:
        """Remote execution of the verifier function with SHA-based bundle caching."""
        response = self.remote_with_response(env, *args, **kwargs)

        # Handle response
        if response.stdout:
            print(response.stdout)
        if response.success:
            return self._process_result(response.result)
        else:
            self._raise_remote_error(response.error)

    def _process_result(self, result: Any) -> float:
        """Process remote execution result, handling different return types."""
        # Handle different return types like local execution
        if isinstance(result, (int, float)):
            return float(result)
        elif isinstance(result, dict) and "score" in result:
            return float(result["score"])
        else:
            # Try to extract score from object attributes
            if hasattr(result, "score"):
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
        except Exception:
            raise RuntimeError(full_message)

    def _get_env_id(self, env: "SyncEnv") -> str:
        """Generate a unique identifier for the environment."""
        # Use instance base URL or similar unique identifier
        if hasattr(env, "instance") and hasattr(env.instance, "base_url"):
            return f"{env.instance.base_url}"
        else:
            # Fallback to object id (less ideal but works)
            return str(id(env))

    def _is_bundle_not_found_error(self, error: Exception) -> bool:
        """Check if the error indicates the bundle was not found on the server."""
        # Check for common "bundle not found" error patterns
        error_msg = str(error).lower()
        return (
            "bundle not found" in error_msg
            or "verifier not found" in error_msg
            or "404" in error_msg
            or "not found" in error_msg
        )

    def remote_with_response(
        self, env: "SyncEnv", *args, **kwargs
    ) -> "VerifiersExecuteResponse":
        """Remote execution of the verifier function that returns the full response model."""
        args_array = list(args)
        # Send complete environment data for remote reconstruction
        env_data = {
            "instance_id": env.instance_id,
            "env_key": env.env_key,
            "version": env.version,
            "status": env.status,
            "subdomain": env.subdomain,
            "created_at": env.created_at,
            "updated_at": env.updated_at,
            "terminated_at": env.terminated_at,
            "team_id": env.team_id,
            "region": env.region,
            "env_variables": env.env_variables,
            "data_key": env.data_key,
            "data_version": env.data_version,
            "urls": env.urls.model_dump() if env.urls else None,
            "health": env.health,
        }
        args_array.append({"env": env_data})
        args = tuple(args_array)

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
                    args_array=args_array,
                    kwargs=kwargs,
                    needs_upload=True,
                )

                logger.debug(f"Bundle {bundle_sha[:8]}... uploaded successfully")
                return response

            else:
                # Bundle already available - execute without upload
                logger.info(f"Bundle {bundle_sha[:8]}... already cached for {self.key}")
                response = env.execute_verifier_remote(
                    bundle_data=b"",  # Empty bundle since it's cached
                    bundle_sha=bundle_sha,
                    key=self.key,
                    function_name=self.func.__name__,
                    args=args,
                    args_array=args_array,
                    kwargs=kwargs,
                    needs_upload=False,
                )
                return response

        except Exception as e:
            # Check if error indicates bundle not found and retry with upload
            if self._is_bundle_not_found_error(e) and not needs_upload:
                logger.info(
                    f"Bundle {bundle_sha[:8]}... not found on server, uploading..."
                )
                bundle_data, _ = self._get_or_create_bundle()
                response = env.execute_verifier_remote(
                    bundle_data=bundle_data,
                    bundle_sha=bundle_sha,
                    key=self.key,
                    function_name=self.func.__name__,
                    args=args,
                    args_array=args_array,
                    kwargs=kwargs,
                    needs_upload=True,
                )
                return response
            else:
                logger.error(f"Error in remote execution of {self.key}: {e}")
                raise


def verifier(
    key: Optional[str] = None,
    extra_requirements: Optional[List[str]] = None,
    sha256: Optional[str] = None,
    raw_code: Optional[str] = None,
) -> Callable[[F], SyncVerifierFunction]:
    """
    Decorator to create a verifier function with env-first pattern.

    The decorated function must take 'env' as its first parameter, making it explicit
    that verifiers operate within an environment context. This makes verifiers reusable
    across different environments.

    Args:
        key: Optional key for the verifier. Defaults to function name.
        extra_requirements: Additional PyPI packages needed by the verifier.
        sha256: Optional SHA256 hash of existing server-side bundle to use.
        raw_code: Optional raw code to use as bundle (bypasses source extraction).

    Example:
        # Synchronous verifier (works locally and remotely)
        @verifier(key="check_user_count")
        def check_user_count(env, expected_count: int) -> float:
            db = env.db()
            result = db.query("SELECT COUNT(*) FROM users")
            actual_count = result.rows[0][0]
            return 1.0 if actual_count >= expected_count else 0.0

        # Async verifier (only works locally)
        @verifier(key="check_user_async")
        async def check_user_async(env, expected_count: int) -> float:
            db = env.db()
            result = await db.query("SELECT COUNT(*) FROM users")
            actual_count = result.rows[0][0]
            return 1.0 if actual_count >= expected_count else 0.0

        # Usage
        env = await fleet.env.make_async("fira")

        # Local execution
        result = await check_user_count(env, 5)        # sync verifier
        result = await check_user_async(env, 5)       # async verifier

        # Remote execution
        result = await check_user_count.remote(env, 5) # sync verifier works
        # await check_user_async.remote(env, 5)        # raises NotImplementedError
    """

    def decorator(func: F) -> SyncVerifierFunction:
        verifier_key = key or func.__name__
        verifier_uuid = str(uuid.uuid4())

        return SyncVerifierFunction(
            func, verifier_key, extra_requirements, verifier_uuid, sha256, raw_code
        )

    return decorator
