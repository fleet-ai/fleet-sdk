from unittest.mock import AsyncMock, Mock

import pytest

from fleet._async.judge import AsyncJudge
from fleet.judge import SyncJudge


class _Response:
    def json(self) -> dict:
        return {"normalized_score": 1.0}


def test_sync_judge_sends_cost_team_and_auth_headers(monkeypatch):
    monkeypatch.setenv("FLEET_JUDGE_TOKEN", "judge-token")
    monkeypatch.setenv("FLEET_COST_TEAM_ID", "11111111-1111-4111-8111-111111111111")
    client = Mock()
    client.request.return_value = _Response()

    SyncJudge(client, "instance-1").grade("rubric", "submission")

    assert client.request.call_args.kwargs["extra_headers"] == {
        "X-Fleet-Judge-Token": "judge-token",
        "X-Fleet-Cost-Team-ID": "11111111-1111-4111-8111-111111111111",
    }


@pytest.mark.asyncio
async def test_async_judge_sends_cost_team_and_auth_headers(monkeypatch):
    monkeypatch.setenv("FLEET_JUDGE_TOKEN", "judge-token")
    monkeypatch.setenv("FLEET_COST_TEAM_ID", "22222222-2222-4222-8222-222222222222")
    client = Mock()
    client.request = AsyncMock(return_value=_Response())

    await AsyncJudge(client, "instance-1").grade("rubric", "submission")

    assert client.request.call_args.kwargs["extra_headers"] == {
        "X-Fleet-Judge-Token": "judge-token",
        "X-Fleet-Cost-Team-ID": "22222222-2222-4222-8222-222222222222",
    }


def test_sync_judge_omits_blank_cost_team_header(monkeypatch):
    monkeypatch.setenv("FLEET_JUDGE_TOKEN", "judge-token")
    monkeypatch.setenv("FLEET_COST_TEAM_ID", "   ")
    client = Mock()
    client.request.return_value = _Response()

    SyncJudge(client, "instance-1").grade("rubric", "submission")

    assert client.request.call_args.kwargs["extra_headers"] == {
        "X-Fleet-Judge-Token": "judge-token"
    }
