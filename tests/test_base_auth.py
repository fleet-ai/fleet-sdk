from __future__ import annotations

import pytest

from fleet._async.base import BaseWrapper as AsyncBaseWrapper
from fleet._async.exceptions import FleetAuthenticationError as AsyncAuthError
from fleet._auth_headers import AuthenticatedWrapperMixin
from fleet.base import BaseWrapper as SyncBaseWrapper
from fleet.exceptions import FleetAuthenticationError as SyncAuthError


def test_sync_and_async_base_wrappers_share_auth_header_mixin():
    assert issubclass(SyncBaseWrapper, AuthenticatedWrapperMixin)
    assert issubclass(AsyncBaseWrapper, AuthenticatedWrapperMixin)


@pytest.mark.parametrize(
    "wrapper_cls,error_cls",
    [
        (SyncBaseWrapper, SyncAuthError),
        (AsyncBaseWrapper, AsyncAuthError),
    ],
)
def test_shared_auth_headers_support_api_key(wrapper_cls, error_cls):
    wrapper = wrapper_cls(
        api_key="fleet-api-key",
        base_url="https://api.example.com",
    )

    headers = wrapper.get_headers()

    assert headers["Authorization"] == "Bearer fleet-api-key"

    wrapper.api_key = None
    with pytest.raises(error_cls):
        wrapper.get_headers()


@pytest.mark.parametrize("wrapper_cls", [SyncBaseWrapper, AsyncBaseWrapper])
def test_shared_auth_headers_support_jwt_team(wrapper_cls):
    wrapper = wrapper_cls(
        api_key=None,
        jwt="jwt-token",
        team_id="team-1",
        base_url="https://api.example.com",
    )

    headers = wrapper.get_headers()

    assert headers["X-JWT-Token"] == "jwt-token"
    assert headers["X-Team-ID"] == "team-1"
    assert "Authorization" not in headers


@pytest.mark.parametrize("wrapper_cls", [SyncBaseWrapper, AsyncBaseWrapper])
def test_shared_auth_headers_prefer_api_key_over_jwt(wrapper_cls):
    wrapper = wrapper_cls(
        api_key="fleet-api-key",
        jwt="jwt-token",
        team_id="team-1",
        base_url="https://api.example.com",
    )

    headers = wrapper.get_headers()

    assert headers["Authorization"] == "Bearer fleet-api-key"
    assert "X-JWT-Token" not in headers
    assert "X-Team-ID" not in headers
