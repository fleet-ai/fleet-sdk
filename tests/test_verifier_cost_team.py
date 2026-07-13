from types import SimpleNamespace

import pytest

from fleet._async.client import _execute_verifier_remote as execute_async
from fleet._async.verifiers.verifier import AsyncVerifierFunction
from fleet.client import _execute_verifier_remote as execute_sync
from fleet.verifiers.verifier import SyncVerifierFunction


TEAM_ID = "11111111-2222-3333-4444-555555555555"
EXECUTE_RESPONSE = {"success": True, "execution_time_ms": 1}


class AsyncClientStub:
    def __init__(self):
        self.request_json = None

    async def request(self, method, path, *, json):
        assert (method, path) == ("POST", "/v1/verifiers/execute")
        self.request_json = json
        return SimpleNamespace(json=lambda: EXECUTE_RESPONSE)


class SyncClientStub:
    def __init__(self):
        self.request_json = None

    def request(self, method, path, *, json):
        assert (method, path) == ("POST", "/v1/verifiers/execute")
        self.request_json = json
        return SimpleNamespace(json=lambda: EXECUTE_RESPONSE)


@pytest.mark.asyncio
async def test_async_execute_sends_cost_team_id_as_request_metadata():
    client = AsyncClientStub()

    await execute_async(
        client,
        bundle_data=b"",
        bundle_sha="sha",
        key="key",
        function_name="verify",
        args=(),
        args_array=[],
        kwargs={"final_answer": "done"},
        needs_upload=False,
        cost_team_id=TEAM_ID,
    )

    assert client.request_json["cost_team_id"] == TEAM_ID


def test_sync_execute_sends_cost_team_id_as_request_metadata():
    client = SyncClientStub()

    execute_sync(
        client,
        bundle_data=b"",
        bundle_sha="sha",
        key="key",
        function_name="verify",
        args=(),
        args_array=[],
        kwargs={"final_answer": "done"},
        needs_upload=False,
        cost_team_id=TEAM_ID,
    )

    assert client.request_json["cost_team_id"] == TEAM_ID


@pytest.mark.asyncio
async def test_async_verifier_keeps_cost_team_id_out_of_function_kwargs(monkeypatch):
    verifier = AsyncVerifierFunction(lambda env, **kwargs: 1.0, key="key")

    async def bundle_status(_env):
        return "sha", False

    monkeypatch.setattr(verifier, "_check_bundle_status", bundle_status)
    captured = {}

    class EnvStub:
        instance_id = "instance"

        async def execute_verifier_remote(self, **kwargs):
            captured.update(kwargs)
            return EXECUTE_RESPONSE

    await verifier.remote_with_response(
        EnvStub(), final_answer="done", cost_team_id=TEAM_ID
    )

    assert captured["cost_team_id"] == TEAM_ID
    assert captured["kwargs"] == {"final_answer": "done"}


def test_sync_verifier_keeps_cost_team_id_out_of_function_kwargs(monkeypatch):
    verifier = SyncVerifierFunction(lambda env, **kwargs: 1.0, key="key")
    monkeypatch.setattr(verifier, "_check_bundle_status", lambda _env: ("sha", False))
    captured = {}

    class EnvStub:
        instance_id = "instance"

        def execute_verifier_remote(self, **kwargs):
            captured.update(kwargs)
            return EXECUTE_RESPONSE

    verifier.remote_with_response(EnvStub(), final_answer="done", cost_team_id=TEAM_ID)

    assert captured["cost_team_id"] == TEAM_ID
    assert captured["kwargs"] == {"final_answer": "done"}


@pytest.mark.asyncio
async def test_async_execute_omits_cost_team_id_when_unspecified():
    client = AsyncClientStub()

    await execute_async(
        client,
        bundle_data=b"",
        bundle_sha="sha",
        key="key",
        function_name="verify",
        args=(),
        args_array=[],
        kwargs={},
        needs_upload=False,
    )

    assert "cost_team_id" not in client.request_json


def test_sync_execute_omits_cost_team_id_when_unspecified():
    client = SyncClientStub()

    execute_sync(
        client,
        bundle_data=b"",
        bundle_sha="sha",
        key="key",
        function_name="verify",
        args=(),
        args_array=[],
        kwargs={},
        needs_upload=False,
    )

    assert "cost_team_id" not in client.request_json


@pytest.mark.asyncio
async def test_async_execute_preserves_existing_positional_async_arguments():
    client = AsyncClientStub()

    await execute_async(
        client,
        b"",
        "sha",
        "key",
        "verify",
        (),
        [],
        {},
        30,
        False,
        None,
        True,
        0.01,
    )

    assert client.request_json["async"] is True
    assert "cost_team_id" not in client.request_json


def test_sync_execute_preserves_existing_positional_async_arguments():
    client = SyncClientStub()

    execute_sync(
        client,
        b"",
        "sha",
        "key",
        "verify",
        (),
        [],
        {},
        30,
        False,
        None,
        True,
        0.01,
    )

    assert client.request_json["async"] is True
    assert "cost_team_id" not in client.request_json
