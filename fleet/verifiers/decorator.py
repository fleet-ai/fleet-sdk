"""Fleet SDK Verifier Decorator - Async Version.

Provides a @verifier decorator that can wrap any sync function to support
both local execution and remote execution via .remote() method.
"""

import inspect
import functools
import traceback
import asyncio
from typing import Any, Callable, Dict, Optional, TypeVar, Union
import uuid
import logging

logger = logging.getLogger(__name__)

F = TypeVar('F', bound=Callable[..., Any])





class SyncVerifiedFunction:
    """Wrapper for a verified function that supports local execution with env-first pattern."""
    
    def __init__(
        self,
        func: F,
        name: str,
        verifier_id: str
    ):
        self.func = func
        self.name = name
        self.verifier_id = verifier_id
        
        # Copy function metadata
        functools.update_wrapper(self, func)
    
    def __call__(self, env, *args, **kwargs) -> float:
        """Local execution of the verifier function with env as first parameter."""
        try:
            result = self.func(env, *args, **kwargs)
            
            # Handle different return types
            if isinstance(result, (int, float)):
                # Direct score return
                return float(result)
            elif isinstance(result, dict) and "score" in result:
                return float(result["score"])
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

def verifier(
    name: Optional[str] = None,
    verifier_id: Optional[str] = None
) -> Callable[[F], SyncVerifiedFunction]:
    """
    Decorator to create a verifier function with env-first pattern.
    
    The decorated function must take 'env' as its first parameter, making it explicit
    that verifiers operate within an environment context. This makes verifiers reusable
    across different environments.
    
    Args:
        name: Optional name for the verifier. Defaults to function name.
        verifier_id: Optional unique ID for the verifier. Defaults to generated UUID.
    
    Example:
        @verifier(name="test_database_state")
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
    """
    def decorator(func: F) -> SyncVerifiedFunction:
        verifier_name = name or func.__name__
        verifier_uuid = verifier_id or str(uuid.uuid4())
        
        return SyncVerifiedFunction(
            func,
            verifier_name,
            verifier_uuid
        )
    
    return decorator