"""Fleet SDK Type Definitions.

This file contains type definitions that are shared between async and sync versions.
It is not processed by unasync, so we can define union types that work correctly
for both async and sync verifier functions.
"""

from __future__ import annotations

from typing import Union, TYPE_CHECKING

if TYPE_CHECKING:
    from .verifiers import SyncVerifiedFunction
    from ._async.verifiers import AsyncVerifiedFunction

# Union type to support both async and sync verifiers
# This definition works for both the async and sync versions of the codebase
VerifierFunction = Union["AsyncVerifiedFunction", "SyncVerifiedFunction"] 