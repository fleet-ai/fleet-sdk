"""Tests for instance-create wait declaration and duplicate-request recovery.

Covers Fleet.make() / AsyncFleet.make():
- max_wait_seconds derived from the create timeout (timeout - margin, capped)
- explicit max_wait_seconds wins over derivation
- the create request uses the create timeout, not the client default
- 409 duplicate_request_id with an instance_id pointer recovers the original
  instance; a 409 without a pointer is re-raised
"""

import pytest
from unittest.mock import AsyncMock, Mock, patch

from fleet.client import Fleet
from fleet._async.client import AsyncFleet
from fleet.config import CREATE_MAX_WAIT_MARGIN_S, DEFAULT_CREATE_TIMEOUT
from fleet.exceptions import FleetConflictError as SyncFleetConflictError
from fleet._async.exceptions import FleetConflictError as AsyncFleetConflictError


def _instance_payload(instance_id: str = "inst-123", status: str = "running") -> dict:
    return {
        "instance_id": instance_id,
        "env_key": "fira",
        "version": "v0.0.69",
        "status": status,
        "subdomain": f"{instance_id}.us-east-1",
        "created_at": "2026-07-17T00:00:00Z",
        "updated_at": "2026-07-17T00:00:00Z",
        "terminated_at": None,
        "team_id": "team-1",
        "region": "us-east-1",
        "env_variables": None,
        "data_key": None,
        "data_version": None,
        "urls": None,
        "health": True,
    }


def _response_with(payload: dict) -> Mock:
    response = Mock()
    response.json.return_value = payload
    return response


@pytest.fixture
def fleet_client():
    with patch("fleet.client.default_httpx_client") as mock_factory:
        mock_factory.return_value = Mock()
        client = Fleet(api_key="test_key")
        client.client.request = Mock(return_value=_response_with(_instance_payload()))
        yield client


@pytest.fixture
def async_fleet_client():
    with patch("fleet._async.client.default_httpx_client") as mock_factory:
        mock_factory.return_value = Mock()
        client = AsyncFleet(api_key="test_key")
        client.client.request = AsyncMock(
            return_value=_response_with(_instance_payload())
        )
        yield client


def _create_call(mock_request) -> dict:
    call = mock_request.call_args
    assert call.args[0] == "POST"
    assert call.args[1] == "/v1/env/instances"
    return call.kwargs


class TestMakeWaitDeclaration:
    def test_default_timeout_declares_wait(self, fleet_client):
        fleet_client.make("fira")
        kwargs = _create_call(fleet_client.client.request)
        assert kwargs["timeout"] == DEFAULT_CREATE_TIMEOUT
        assert kwargs["json"]["max_wait_seconds"] == (
            int(DEFAULT_CREATE_TIMEOUT) - CREATE_MAX_WAIT_MARGIN_S
        )

    def test_explicit_timeout_derives_wait(self, fleet_client):
        fleet_client.make("fira", timeout=300.0)
        kwargs = _create_call(fleet_client.client.request)
        assert kwargs["timeout"] == 300.0
        assert kwargs["json"]["max_wait_seconds"] == 300 - CREATE_MAX_WAIT_MARGIN_S

    def test_explicit_max_wait_wins(self, fleet_client):
        fleet_client.make("fira", timeout=300.0, max_wait_seconds=120)
        kwargs = _create_call(fleet_client.client.request)
        assert kwargs["json"]["max_wait_seconds"] == 120

    def test_max_wait_capped_at_3600(self, fleet_client):
        fleet_client.make("fira", timeout=7200.0)
        kwargs = _create_call(fleet_client.client.request)
        assert kwargs["json"]["max_wait_seconds"] == 3600

    def test_tiny_timeout_floors_at_zero(self, fleet_client):
        fleet_client.make("fira", timeout=10.0)
        kwargs = _create_call(fleet_client.client.request)
        assert kwargs["json"]["max_wait_seconds"] == 0

    async def test_async_default_timeout_declares_wait(self, async_fleet_client):
        await async_fleet_client.make("fira")
        kwargs = _create_call(async_fleet_client.client.request)
        assert kwargs["timeout"] == DEFAULT_CREATE_TIMEOUT
        assert kwargs["json"]["max_wait_seconds"] == (
            int(DEFAULT_CREATE_TIMEOUT) - CREATE_MAX_WAIT_MARGIN_S
        )


class TestMakeDuplicateRecovery:
    @pytest.fixture(autouse=True)
    def fast_recovery(self, monkeypatch):
        import fleet.client as sync_client
        import fleet._async.client as async_client

        for mod in (sync_client, async_client):
            monkeypatch.setattr(mod, "DUPLICATE_RECOVERY_POLL_INTERVAL_S", 0.001)
            monkeypatch.setattr(mod, "DUPLICATE_RECOVERY_MIN_BUDGET_S", 0.05)

    def _conflict(self, cls=SyncFleetConflictError):
        return cls(
            "Request with ID 'abc' has already been processed.",
            instance_id="inst-orig",
        )

    def test_conflict_with_running_pointer_recovers_instance(self, fleet_client):
        fleet_client.client.request.side_effect = [
            self._conflict(),
            _response_with(_instance_payload("inst-orig")),
        ]

        env = fleet_client.make("fira")

        assert env.instance_id == "inst-orig"
        recovery_call = fleet_client.client.request.call_args_list[1]
        assert recovery_call.args[0] == "GET"
        assert recovery_call.args[1] == "/v1/env/instances/inst-orig"

    def test_conflict_with_pending_pointer_polls_until_running(self, fleet_client):
        fleet_client.client.request.side_effect = [
            self._conflict(),
            _response_with(_instance_payload("inst-orig", status="pending")),
            _response_with(_instance_payload("inst-orig", status="pending")),
            _response_with(_instance_payload("inst-orig", status="running")),
        ]

        env = fleet_client.make("fira")

        assert env.instance_id == "inst-orig"
        assert env.status == "running"
        assert fleet_client.client.request.call_count == 4

    def test_conflict_with_error_pointer_raises(self, fleet_client):
        fleet_client.client.request.side_effect = [
            self._conflict(),
            _response_with(_instance_payload("inst-orig", status="error")),
        ]

        with pytest.raises(SyncFleetConflictError) as exc_info:
            fleet_client.make("fira")
        assert exc_info.value.instance_id == "inst-orig"
        assert "'error'" in str(exc_info.value)

    def test_conflict_with_stopped_pointer_raises(self, fleet_client):
        fleet_client.client.request.side_effect = [
            self._conflict(),
            _response_with(_instance_payload("inst-orig", status="stopped")),
        ]

        with pytest.raises(SyncFleetConflictError):
            fleet_client.make("fira")

    def test_conflict_with_stuck_pending_pointer_times_out(self, fleet_client):
        from fleet.exceptions import FleetTimeoutError

        fleet_client.client.request.side_effect = [self._conflict()] + [
            _response_with(_instance_payload("inst-orig", status="pending"))
        ] * 1000

        with pytest.raises(FleetTimeoutError):
            fleet_client.make("fira", timeout=0.1)

    def test_conflict_without_pointer_reraises(self, fleet_client):
        fleet_client.client.request.side_effect = SyncFleetConflictError(
            "Request with ID 'abc' has already been processed."
        )
        with pytest.raises(SyncFleetConflictError):
            fleet_client.make("fira")

    async def test_async_conflict_with_running_pointer_recovers_instance(
        self, async_fleet_client
    ):
        async_fleet_client.client.request.side_effect = [
            self._conflict(AsyncFleetConflictError),
            _response_with(_instance_payload("inst-orig")),
        ]

        env = await async_fleet_client.make("fira")

        assert env.instance_id == "inst-orig"
        recovery_call = async_fleet_client.client.request.call_args_list[1]
        assert recovery_call.args[0] == "GET"
        assert recovery_call.args[1] == "/v1/env/instances/inst-orig"

    async def test_async_conflict_with_pending_pointer_polls_until_running(
        self, async_fleet_client
    ):
        async_fleet_client.client.request.side_effect = [
            self._conflict(AsyncFleetConflictError),
            _response_with(_instance_payload("inst-orig", status="pending")),
            _response_with(_instance_payload("inst-orig", status="running")),
        ]

        env = await async_fleet_client.make("fira")

        assert env.status == "running"
        assert async_fleet_client.client.request.call_count == 3

    async def test_async_conflict_with_error_pointer_raises(self, async_fleet_client):
        async_fleet_client.client.request.side_effect = [
            self._conflict(AsyncFleetConflictError),
            _response_with(_instance_payload("inst-orig", status="error")),
        ]

        with pytest.raises(AsyncFleetConflictError) as exc_info:
            await async_fleet_client.make("fira")
        assert exc_info.value.instance_id == "inst-orig"

    async def test_async_conflict_with_stuck_pending_pointer_times_out(
        self, async_fleet_client
    ):
        from fleet._async.exceptions import FleetTimeoutError as AsyncFleetTimeoutError

        async_fleet_client.client.request.side_effect = [
            self._conflict(AsyncFleetConflictError)
        ] + [_response_with(_instance_payload("inst-orig", status="pending"))] * 1000

        with pytest.raises(AsyncFleetTimeoutError):
            await async_fleet_client.make("fira", timeout=0.1)


class TestConflictErrorParsing:
    def test_sync_409_detail_carries_instance_pointer(self):
        from fleet.base import SyncWrapper

        wrapper = SyncWrapper.__new__(SyncWrapper)
        response = Mock()
        response.status_code = 409
        response.json.return_value = {
            "detail": {
                "error": "duplicate_request_id",
                "message": "Request with ID 'abc' has already been processed.",
                "instance_id": "inst-orig",
            }
        }
        with pytest.raises(SyncFleetConflictError) as exc_info:
            wrapper._handle_error_response(response)
        assert exc_info.value.instance_id == "inst-orig"

    def test_async_409_detail_carries_instance_pointer(self):
        from fleet._async.base import AsyncWrapper

        wrapper = AsyncWrapper.__new__(AsyncWrapper)
        response = Mock()
        response.status_code = 409
        response.json.return_value = {
            "detail": {
                "error": "duplicate_request_id",
                "message": "Request with ID 'abc' has already been processed.",
                "instance_id": "inst-orig",
            }
        }
        with pytest.raises(AsyncFleetConflictError) as exc_info:
            wrapper._handle_error_response(response)
        assert exc_info.value.instance_id == "inst-orig"

    def test_sync_409_without_structured_detail(self):
        from fleet.base import SyncWrapper

        wrapper = SyncWrapper.__new__(SyncWrapper)
        response = Mock()
        response.status_code = 409
        response.json.return_value = {"detail": "resource 'foo' already exists"}
        with pytest.raises(SyncFleetConflictError) as exc_info:
            wrapper._handle_error_response(response)
        assert exc_info.value.instance_id is None
        assert exc_info.value.resource_name == "foo"
