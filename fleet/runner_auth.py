"""Present ``X-Runner-Token`` on calls into an instance's runner.

Fleet's direct-router gates instance routes (``/api/v1/env/*``) on a shared
token. Requests without it are answered 404 on a cluster with the gate enforcing
-- so ``env.db(...).query(...)``, ``instance.reset()`` and the ``/resources``
probe all fail, while the control-plane API keeps working, which makes it look
like the instance is broken rather than the call being unauthorized.

The token is resolved lazily, once per client, in this order:

1. ``RUNNER_AUTH_TOKEN`` in the environment. Services running inside Fleet
   already have it and should make no extra call.
2. ``GET {base_url}/v1/runner-auth/token``, authenticated with whatever the
   caller already uses for the control plane. The auth headers come from the
   control-plane wrapper itself rather than being rebuilt here, so API keys and
   ``flt login`` JWTs both work -- rebuilding them would have silently covered
   only api_key callers.

Fetching rather than embedding is deliberate. The value is not a secret in the
usual sense, but one party must never hold it: the agent running inside an
environment container. Shipping it in this package would hand it to exactly that
party, since an agent can install the SDK. Serving it only to a caller with an
API key keeps the channel closed -- an environment container carries no Fleet
credentials.

Every failure is soft. No API key, a 404 (deployment has no gate configured), a
timeout, any error: send no header, which is exactly the behaviour before this
existed and is correct against an ungated router, which ignores the header.
"""

from __future__ import annotations

import os
import re
import threading
from typing import Optional

import httpx

RUNNER_TOKEN_HEADER = "X-Runner-Token"
TOKEN_PATH = "/v1/runner-auth/token"

# Matches the direct-router's predicate exactly. Note the trailing (/|$): a
# substring test would also claim /api/v1/environments, a control-plane route
# that must not receive this token.
_RUNNER_PATH_RE = re.compile(r"^(/[^/]+)?/api/v1/env(/|$)")

# Short: this is one small GET against the control plane, and a slow answer must
# not stall the instance call that triggered it.
_FETCH_TIMEOUT = 10.0

# The control plane accepts two credential shapes and get_headers() emits
# whichever applies: an API key becomes Authorization, while an `flt login`
# session becomes X-JWT-Token + X-Team-ID. Checking only Authorization looked
# right and silently excluded every logged-in user -- their headers were valid,
# got discarded as "no credential", and the resulting miss was cached, so gated
# instance calls kept going out bare. Keyed off the header names the wrapper
# actually sets.
_CREDENTIAL_HEADERS = ("Authorization", "X-JWT-Token")


def is_runner_path(path: Optional[str]) -> bool:
    """True for the instance-runner routes the router gates."""
    return bool(path) and bool(_RUNNER_PATH_RE.match(path))


def _token_from_env() -> Optional[str]:
    token = (os.environ.get("RUNNER_AUTH_TOKEN") or "").strip()
    return token or None


def _token_from_payload(payload: object) -> Optional[str]:
    if not isinstance(payload, dict):
        return None
    token = payload.get("token")
    if not isinstance(token, str):
        return None
    return token.strip() or None


class RunnerTokenProvider:
    """Resolves the runner token once and remembers the answer.

    Remembers a FAILURE too. Without that, a deployment with no gate configured
    would pay a control-plane round trip on every single instance call, forever
    -- turning an optional feature into a per-request tax on the common path.
    """

    def __init__(self, auth_source) -> None:
        # Duck-typed on purpose: anything exposing get_headers() and base_url
        # works, which is both control-plane wrappers and a test double.
        self._auth = auth_source
        self._token: Optional[str] = None
        self._resolved = False
        self._lock = threading.Lock()

    def _endpoint(self) -> Optional[str]:
        base_url = getattr(self._auth, "base_url", None)
        return f"{str(base_url).rstrip('/')}{TOKEN_PATH}" if base_url else None

    def _headers(self) -> Optional[dict]:
        try:
            headers = self._auth.get_headers()
        except Exception:
            return None
        # No credential means no fetch: an unauthenticated GET would 401 and we
        # would cache a negative for the life of the client.
        if not any(headers.get(name) for name in _CREDENTIAL_HEADERS):
            return None
        return headers

    def token(self) -> Optional[str]:
        if self._resolved:
            return self._token
        with self._lock:
            if self._resolved:
                return self._token
            self._token = self._resolve()
            self._resolved = True
            return self._token

    def _resolve(self) -> Optional[str]:
        env_token = _token_from_env()
        if env_token:
            return env_token
        endpoint, headers = self._endpoint(), self._headers()
        if not endpoint or not headers:
            return None
        try:
            # A separate client on purpose: this can be called from inside a
            # request hook on the shared client, and reusing it there would
            # recurse.
            with httpx.Client(timeout=_FETCH_TIMEOUT) as client:
                response = client.get(endpoint, headers=headers)
            if response.status_code != 200:
                return None
            return _token_from_payload(response.json())
        except Exception:
            # Soft by design; see the module docstring.
            return None

    async def token_async(self) -> Optional[str]:
        if self._resolved:
            return self._token
        env_token = _token_from_env()
        if env_token:
            self._token, self._resolved = env_token, True
            return self._token
        endpoint, headers = self._endpoint(), self._headers()
        if not endpoint or not headers:
            self._token, self._resolved = None, True
            return None
        token: Optional[str] = None
        try:
            async with httpx.AsyncClient(timeout=_FETCH_TIMEOUT) as client:
                response = await client.get(endpoint, headers=headers)
            if response.status_code == 200:
                token = _token_from_payload(response.json())
        except Exception:
            token = None
        # Last write wins rather than holding a lock across an await; the value
        # is idempotent, so a concurrent double-fetch costs one extra GET and
        # settles on the same answer.
        self._token, self._resolved = token, True
        return token
