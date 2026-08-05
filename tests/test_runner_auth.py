"""The SDK must present X-Runner-Token on instance calls, and fail soft always.

Fleet's direct-router gates /api/v1/env/* on a shared token. Before this, the
SDK sent no credential to instances at all, so env.db().query() and
instance.reset() were 404'd on an enforcing cluster while the control-plane API
kept working -- which reads as a broken instance, not an unauthorized call.

The failure modes matter more than the happy path here. This ships to users on
clusters that may have no gate at all, so every way of not getting a token has
to end in "send no header", never an exception and never a stall.
"""

from __future__ import annotations

import httpx
import pytest

from fleet.runner_auth import (
    RUNNER_TOKEN_HEADER,
    RunnerTokenProvider,
    is_runner_path,
)


class _Auth:
    """Stands in for a control-plane wrapper: get_headers() + base_url.

    ``mode`` mirrors the two credential shapes the real wrapper emits -- an API
    key becomes Authorization, an `flt login` session becomes X-JWT-Token plus
    X-Team-ID and no Authorization at all.
    """

    def __init__(self, base_url="https://orchestrator.fleetai.com", mode="api_key"):
        self.base_url = base_url
        self._mode = mode

    def get_headers(self):
        if self._mode == "api_key":
            return {"Authorization": "Bearer sk-test"}
        if self._mode == "jwt":
            return {"X-JWT-Token": "jwt-abc", "X-Team-ID": "team-1"}
        return {}


@pytest.fixture(autouse=True)
def _no_ambient_token(monkeypatch):
    """The env var wins over the fetch, so leaving it set would mask everything."""
    monkeypatch.delenv("RUNNER_AUTH_TOKEN", raising=False)


@pytest.mark.parametrize(
    "path,expected",
    [
        ("/api/v1/env", True),
        ("/api/v1/env/resources", True),
        ("/api/v1/env/resources/sqlite/current/query", True),
        ("/jira/api/v1/env/reset", True),
        # A substring check would claim this control-plane route.
        ("/api/v1/environments/launch", False),
        ("/v1/env/instances", False),
        ("/v1/tasks", False),
    ],
)
def test_runner_path_predicate(path, expected):
    assert is_runner_path(path) is expected


def test_env_var_wins_and_makes_no_network_call(monkeypatch):
    """Services inside Fleet already hold the token; they must not pay a fetch."""
    monkeypatch.setenv("RUNNER_AUTH_TOKEN", "tok-from-env")

    def _explode(*_a, **_k):
        raise AssertionError("fetched despite RUNNER_AUTH_TOKEN being set")

    monkeypatch.setattr(httpx, "Client", _explode)
    assert RunnerTokenProvider(_Auth()).token() == "tok-from-env"


def test_fetches_with_the_callers_credentials(monkeypatch):
    seen = {}

    class _Client:
        def __init__(self, **_kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def get(self, url, headers=None):
            seen["url"], seen["headers"] = url, headers
            return httpx.Response(200, json={"token": "tok-fetched"})

    monkeypatch.setattr(httpx, "Client", _Client)

    assert RunnerTokenProvider(_Auth()).token() == "tok-fetched"
    assert seen["url"] == "https://orchestrator.fleetai.com/v1/runner-auth/token"
    # Reuses the wrapper's own auth, so flt-login JWTs work too, not just keys.
    assert seen["headers"]["Authorization"] == "Bearer sk-test"


def test_resolves_once_and_caches_the_answer(monkeypatch):
    calls = {"n": 0}

    class _Client:
        def __init__(self, **_kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def get(self, *_a, **_k):
            calls["n"] += 1
            return httpx.Response(200, json={"token": "tok"})

    monkeypatch.setattr(httpx, "Client", _Client)
    provider = RunnerTokenProvider(_Auth())

    assert [provider.token() for _ in range(5)] == ["tok"] * 5
    assert calls["n"] == 1


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(404, json={"detail": "no gate configured"}),
        httpx.Response(401, json={"detail": "nope"}),
        httpx.Response(500, text="boom"),
        httpx.Response(200, json={"nothing": "useful"}),
        httpx.Response(200, json={"token": "   "}),
    ],
)
def test_every_bad_answer_yields_no_token(monkeypatch, response):
    class _Client:
        def __init__(self, **_kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def get(self, *_a, **_k):
            return response

    monkeypatch.setattr(httpx, "Client", _Client)
    assert RunnerTokenProvider(_Auth()).token() is None


def test_a_raising_transport_is_not_propagated(monkeypatch):
    """A control plane that is down must not break instance calls that would
    have worked fine on an ungated cluster."""

    class _Client:
        def __init__(self, **_kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def get(self, *_a, **_k):
            raise httpx.ConnectTimeout("down")

    monkeypatch.setattr(httpx, "Client", _Client)
    assert RunnerTokenProvider(_Auth()).token() is None


def test_a_failed_resolution_is_also_cached(monkeypatch):
    """Otherwise a deployment with no gate pays a round trip on every call."""
    calls = {"n": 0}

    class _Client:
        def __init__(self, **_kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def get(self, *_a, **_k):
            calls["n"] += 1
            return httpx.Response(404)

    monkeypatch.setattr(httpx, "Client", _Client)
    provider = RunnerTokenProvider(_Auth())

    assert provider.token() is None
    assert provider.token() is None
    assert calls["n"] == 1


def test_jwt_sessions_also_fetch(monkeypatch):
    """`flt login` sends X-JWT-Token + X-Team-ID and no Authorization.

    Keying the credential check on Authorization alone looked correct and
    excluded every logged-in user: valid headers were discarded as "no
    credential", the fetch was skipped, and the miss was cached -- so their
    gated instance calls kept going out bare. Caught by Bugbot on the first
    revision of this file.
    """
    seen = {}

    class _Client:
        def __init__(self, **_kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def get(self, url, headers=None):
            seen.update(headers or {})
            return httpx.Response(200, json={"token": "tok-jwt"})

    monkeypatch.setattr(httpx, "Client", _Client)

    assert RunnerTokenProvider(_Auth(mode="jwt")).token() == "tok-jwt"
    assert seen["X-JWT-Token"] == "jwt-abc"
    assert seen["X-Team-ID"] == "team-1"


def test_no_credential_means_no_fetch(monkeypatch):
    """An unauthenticated GET would 401 and poison the cache for the client."""

    def _explode(*_a, **_k):
        raise AssertionError("fetched with no Authorization header")

    monkeypatch.setattr(httpx, "Client", _explode)
    assert RunnerTokenProvider(_Auth(mode="none")).token() is None


def test_no_base_url_means_no_fetch(monkeypatch):
    def _explode(*_a, **_k):
        raise AssertionError("fetched with no base_url")

    monkeypatch.setattr(httpx, "Client", _explode)
    assert RunnerTokenProvider(_Auth(base_url=None)).token() is None


async def test_async_resolution(monkeypatch):
    class _Client:
        def __init__(self, **_kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def get(self, *_a, **_k):
            return httpx.Response(200, json={"token": "tok-async"})

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    assert await RunnerTokenProvider(_Auth()).token_async() == "tok-async"


async def test_async_failure_is_soft(monkeypatch):
    class _Client:
        def __init__(self, **_kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def get(self, *_a, **_k):
            raise httpx.ConnectTimeout("down")

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    assert await RunnerTokenProvider(_Auth()).token_async() is None


def test_wrapper_attaches_the_token_to_instance_requests(monkeypatch):
    """End of the chain: the header must reach the wire, not just the provider."""
    from fleet.instance.base import SyncWrapper

    monkeypatch.setenv("RUNNER_AUTH_TOKEN", "tok-abc")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"x-echo": request.headers.get(RUNNER_TOKEN_HEADER, "")},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    wrapper = SyncWrapper(
        url="https://inst.env.test.fleetai.com/api/v1/env",
        httpx_client=client,
        runner_token_provider=RunnerTokenProvider(_Auth()),
    )

    assert wrapper.request("GET", "/resources").headers["x-echo"] == "tok-abc"


def test_wrapper_without_a_provider_is_unchanged():
    """An InstanceClient built directly still works with no token and no fetch."""
    from fleet.instance.base import SyncWrapper

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"x-echo": request.headers.get(RUNNER_TOKEN_HEADER, "")}
        )

    wrapper = SyncWrapper(
        url="https://inst.env.test.fleetai.com/api/v1/env",
        httpx_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert wrapper.request("GET", "/resources").headers["x-echo"] == ""
