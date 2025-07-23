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
import asyncio
import inspect
import ast
import textwrap
from typing import Any, Callable, Dict, Optional, List, TypeVar, Set, Union

from .bundler import FunctionBundler
from ..client import AsyncEnvironment

logger = logging.getLogger(__name__)

F = TypeVar('F', bound=Callable[..., Any])

# Global cache to track which bundle SHAs have been uploaded to S3
_uploaded_bundle_shas: Set[str] = set()


@functools.lru_cache(maxsize=128)
def _get_bundle_sha(bundle_data: bytes) -> str:
    """Calculate SHA256 hash of bundle data with LRU caching."""
    return hashlib.sha256(bundle_data).hexdigest()


class AsyncToSyncTransformer(ast.NodeTransformer):
    """Transform async functions to sync by removing async/await keywords."""
    
    def visit_AsyncFunctionDef(self, node):
        """Convert async function to regular function."""
        # Create a new FunctionDef node with the same properties
        new_node = ast.FunctionDef(
            name=node.name,
            args=node.args,
            body=node.body,
            decorator_list=[],  # Remove decorators
            returns=node.returns,
            lineno=node.lineno,
            col_offset=node.col_offset,
        )
        # Continue visiting child nodes
        self.generic_visit(new_node)
        return new_node
    
    def visit_Await(self, node):
        """Remove await expressions."""
        # Just return the inner value without await
        return self.visit(node.value)
    
    def visit_AsyncWith(self, node):
        """Convert async with to regular with."""
        new_node = ast.With(
            items=node.items,
            body=node.body,
            lineno=node.lineno,
            col_offset=node.col_offset,
        )
        self.generic_visit(new_node)
        return new_node
    
    def visit_AsyncFor(self, node):
        """Convert async for to regular for."""
        new_node = ast.For(
            target=node.target,
            iter=node.iter,
            body=node.body,
            orelse=node.orelse,
            lineno=node.lineno,
            col_offset=node.col_offset,
        )
        self.generic_visit(new_node)
        return new_node


def create_sync_function_from_async(async_func: Callable) -> Callable:
    """Create a synchronous version of an async function by transforming the AST."""
    try:
        # Get the source code
        source = inspect.getsource(async_func)
        
        # Parse the source into AST
        tree = ast.parse(source)
        
        # Find the async function definition (it should be the first/only one)
        async_func_def = None
        for node in tree.body:
            if isinstance(node, ast.AsyncFunctionDef) and node.name == async_func.__name__:
                async_func_def = node
                break
        
        if not async_func_def:
            raise ValueError(f"Could not find async function definition for {async_func.__name__}")
        
        # Create a new sync function definition
        sync_func_def = ast.FunctionDef(
            name=async_func_def.name,
            args=async_func_def.args,
            body=async_func_def.body,
            decorator_list=[],  # Remove decorators
            returns=async_func_def.returns,
            lineno=1,
            col_offset=0,
        )
        
        # Transform the function body to remove async/await
        transformer = AsyncToSyncTransformer()
        sync_func_def = transformer.visit(sync_func_def)
        
        # Create a module with the function
        module = ast.Module(body=[sync_func_def], type_ignores=[])
        
        # Fix line numbers
        for node in ast.walk(module):
            if hasattr(node, 'lineno'):
                node.lineno = max(1, node.lineno)
            if hasattr(node, 'col_offset'):
                node.col_offset = 0
        
        # Generate the source code for the sync function
        sync_source = ast.unparse(sync_func_def)
        
        # Compile and execute
        code = compile(module, filename=f"<generated_{async_func.__name__}>", mode='exec')
        
        # Create a namespace with necessary imports and constants
        namespace = {
            'TASK_SUCCESSFUL_SCORE': 1.0,
            'TASK_FAILED_SCORE': 0.0,
            '__name__': '__main__',
            '__builtins__': __builtins__,
            'print': print,  # Ensure print is available
        }
        
        # Execute the code to define the function
        exec(code, namespace)
        
        # Get the generated function
        sync_func = namespace[async_func.__name__]
        
        # Store the source code as an attribute for the bundler
        sync_func.__source__ = sync_source
        
        # Copy metadata
        sync_func.__doc__ = f"Auto-generated sync version of {async_func.__name__}"
        sync_func.__module__ = async_func.__module__
        
        logger.info(f"Successfully generated sync version of {async_func.__name__}")
        return sync_func
        
    except Exception as e:
        logger.warning(f"Failed to auto-generate sync version of {async_func.__name__}: {e}")
        
        # Fallback: create a simple sync wrapper that just removes await
        # This works for most Fleet verifiers since db operations are sync in remote env
        def sync_wrapper(env, *args, **kwargs):
            """Auto-generated sync wrapper for remote execution."""
            # Define constants locally for remote execution
            TASK_SUCCESSFUL_SCORE = 1.0
            TASK_FAILED_SCORE = 0.0
            
            # Get the original async function's source
            try:
                source = inspect.getsource(async_func)
                # Simple transformation: remove async def and await keywords
                # This works for Fleet verifiers where env.db() returns sync resources
                source = source.replace('async def', 'def')
                source = source.replace('await ', '')
                
                # Execute the transformed source
                exec_namespace = {
                    'TASK_SUCCESSFUL_SCORE': TASK_SUCCESSFUL_SCORE,
                    'TASK_FAILED_SCORE': TASK_FAILED_SCORE,
                    'print': print,
                    '__builtins__': __builtins__,
                }
                
                exec(source, exec_namespace)
                
                # Get the transformed function
                transformed_func = exec_namespace[async_func.__name__]
                
                # Call it with the provided arguments
                return transformed_func(env, *args, **kwargs)
                
            except Exception as e:
                print(f"⚠️  Remote execution error for '{async_func.__name__}': {e}")
                return TASK_FAILED_SCORE
        
        sync_wrapper.__name__ = async_func.__name__
        sync_wrapper.__doc__ = f"Fallback sync wrapper for {async_func.__name__}"
        
        # Store a simple source representation for the bundler
        sync_wrapper.__source__ = f"""def {async_func.__name__}(env, *args, **kwargs):
    # Auto-generated fallback wrapper
    TASK_SUCCESSFUL_SCORE = 1.0
    TASK_FAILED_SCORE = 0.0
    
    # This is a fallback - the actual implementation failed to convert
    print("⚠️  Using fallback sync wrapper for remote execution")
    return TASK_FAILED_SCORE
"""
        
        return sync_wrapper


class AsyncVerifierFunction:
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
        self._is_async = asyncio.iscoroutinefunction(func)
        
        # Create a sync wrapper function for remote execution
        if self._is_async:
            self._sync_wrapper = create_sync_function_from_async(func)
        else:
            self._sync_wrapper = func
        
        # Copy function metadata
        functools.update_wrapper(self, func)
    
    def _get_or_create_bundle(self) -> tuple[bytes, str]:
        """Get or create bundle data and return (bundle_data, sha)."""
        if self._bundle_data is None or self._bundle_sha is None:
            # Create bundle using the sync wrapper for remote execution
            self._bundle_data = self._bundler.create_bundle(
                self._sync_wrapper,  # Use sync wrapper for bundling
                self.extra_requirements,
                self.verifier_id
            )
            self._bundle_sha = _get_bundle_sha(self._bundle_data)
            logger.debug(f"Created bundle for {self.name} with SHA: {self._bundle_sha}")
        
        return self._bundle_data, self._bundle_sha
    
    async def _check_bundle_status(self, env: AsyncEnvironment) -> tuple[str, bool]:
        """Check if bundle needs to be uploaded and return (sha, needs_upload)."""
        bundle_data, bundle_sha = self._get_or_create_bundle()
        
        # 1. Check local process cache first
        if bundle_sha in _uploaded_bundle_shas:
            logger.debug(f"Bundle {bundle_sha[:8]}... found in local cache")
            return bundle_sha, False  # Already uploaded, no upload needed
        
        # 2. Check if bundle exists on server (pseudocode)
        # TODO: Add endpoint to check if bundle SHA exists in S3
        try:
            exists = await env.check_bundle_exists(bundle_sha)
            if exists.success:
                logger.info(f"Bundle {bundle_sha[:8]}... found on server, updating cache")
                _uploaded_bundle_shas.add(bundle_sha)
                return bundle_sha, False  # Found on server, no upload needed
        except Exception as e:
            logger.warning(f"Failed to check bundle existence: {e}")
        
        # 3. Bundle not found locally or on server - upload needed
        logger.info(f"Bundle {bundle_sha[:8]}... needs to be uploaded")
        return bundle_sha, True  # Upload needed
    
    async def __call__(self, env: AsyncEnvironment, *args, **kwargs) -> float:
        """Local execution of the verifier function with env as first parameter."""
        try:
            if self._is_async:
                # For async functions, await the result
                result = await self.func(env, *args, **kwargs)
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
                if hasattr(result, 'score'):
                    return float(result.score)
                else:
                    raise ValueError(f"Verifier function must return a score (number). Got {type(result)}")
                    
        except Exception as e:
            logger.error(f"Error in verifier {self.name}: {e}")
            # Return error score 0
            return 0.0
    
    async def remote(self, env: AsyncEnvironment, *args, **kwargs) -> float:
        """Remote execution of the verifier function with SHA-based bundle caching."""
        try:
            # Check if bundle needs to be uploaded
            bundle_sha, needs_upload = await self._check_bundle_status(env)
            
            if needs_upload:
                # Need to upload bundle to S3
                logger.info(f"Uploading bundle {bundle_sha[:8]}... for {self.key}")
                bundle_data, _ = self._get_or_create_bundle()
                
                response = await env.execute_verifier_remote(
                    bundle_data=bundle_data,
                    bundle_sha=bundle_sha,
                    key=self.key,
                    function_name=self._sync_wrapper.__name__,  # Use sync wrapper name
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
                
                response = await env.execute_verifier_remote(
                    bundle_data=bundle_data,  # Still need bundle_data for local caching
                    bundle_sha=bundle_sha,
                    key=self.key,
                    function_name=self._sync_wrapper.__name__,  # Use sync wrapper name
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
    
    def _get_env_id(self, env: AsyncEnvironment) -> str:
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
    extra_requirements: Optional[List[str]] = None,
    sync_version: Optional[Callable] = None
) -> Callable[[F], AsyncVerifierFunction]:
    """
    Decorator to create a verifier function with env-first pattern.
    
    The decorated function must take 'env' as its first parameter, making it explicit
    that verifiers operate within an environment context. This makes verifiers reusable
    across different environments.
    
    For async functions, the decorator will automatically create a synchronous version
    for remote execution by removing async/await keywords. This works for most cases
    where the async operations are Fleet resource operations (db, browser, etc).
    
    Args:
        key: Optional key for the verifier. Defaults to function name.
        extra_requirements: Additional PyPI packages needed by the verifier.
        sync_version: Optional synchronous version of an async verifier for remote execution.
                     If not provided, an automatic conversion will be attempted.
    
    Example:
        # Synchronous verifier (works locally and remotely)
        @verifier(key="check_user_count")
        def check_user_count(env, expected_count: int) -> float:
            db = env.db()
            result = db.query("SELECT COUNT(*) FROM users")
            actual_count = result.rows[0][0]
            return 1.0 if actual_count >= expected_count else 0.0
        
        # Async verifier (auto-converted for remote execution)
        @verifier(key="check_user_async")
        async def check_user_async(env, expected_count: int) -> float:
            db = env.db()
            result = await db.query("SELECT COUNT(*) FROM users")
            actual_count = result.rows[0][0]
            return 1.0 if actual_count >= expected_count else 0.0
        
        # Usage
        env = await flt.env.make_async("fira")
        
        # Local execution
        result = await check_user_async(env, 5)
        
        # Remote execution (automatically uses sync version)
        result = await check_user_async.remote(env, 5)
    """
    def decorator(func: F) -> AsyncVerifierFunction:
        verifier_key = key or func.__name__
        verifier_uuid = str(uuid.uuid4())
        
        # If a sync version is provided, use it for remote execution
        if sync_version is not None and asyncio.iscoroutinefunction(func):
            # Create a custom wrapper that uses the sync version for bundling
            wrapper = AsyncVerifierFunction(
                func,
                verifier_key,
                extra_requirements,
                verifier_uuid
            )
            wrapper._sync_wrapper = sync_version
            return wrapper
        
        return AsyncVerifierFunction(
            func,
            verifier_key,
            extra_requirements,
            verifier_uuid
        )
    
    return decorator 