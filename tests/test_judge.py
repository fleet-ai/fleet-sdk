"""Tests for fleet.judge and fleet._async.judge modules."""

import json
import os
from unittest.mock import Mock, patch, MagicMock

import httpx
import pytest

from fleet.judge import (
    Criterion,
    JudgeEndpointConfig,
    JudgeResult,
    JudgeService,
    Rubric,
    get_judge_config,
    _SYSTEM_PROMPT,
)
from fleet._async.judge import AsyncJudgeService


# --- Model tests ---


class TestCriterion:
    def test_basic_creation(self):
        c = Criterion(name="accuracy", max_score=5)
        assert c.name == "accuracy"
        assert c.max_score == 5
        assert c.levels == {}

    def test_with_levels(self):
        c = Criterion(
            name="accuracy",
            max_score=3,
            levels={0: "Wrong", 1: "Partially correct", 3: "Fully correct"},
        )
        assert c.levels[0] == "Wrong"
        assert c.levels[3] == "Fully correct"


class TestRubric:
    def test_creation(self):
        r = Rubric(
            criteria=[
                Criterion(name="quality", max_score=5),
                Criterion(name="style", max_score=3),
            ],
            task_context="Write a poem",
        )
        assert len(r.criteria) == 2
        assert r.task_context == "Write a poem"

    def test_no_context(self):
        r = Rubric(criteria=[Criterion(name="test", max_score=1)])
        assert r.task_context is None


class TestJudgeResult:
    def test_creation(self):
        result = JudgeResult(
            scores={"accuracy": 4.0, "style": 3.0},
            total=7.0,
            max_total=10.0,
            normalized=0.7,
            reasoning={"accuracy": "Good", "style": "Great"},
        )
        assert result.normalized == 0.7
        assert result.scores["accuracy"] == 4.0


class TestJudgeEndpointConfig:
    def test_defaults(self):
        config = JudgeEndpointConfig(
            url="https://api.example.com",
            api_key="sk-test",
        )
        assert config.model == "claude-sonnet-4-20250514"
        assert config.api_format == "anthropic"

    def test_openai_format(self):
        config = JudgeEndpointConfig(
            url="https://api.openai.com",
            api_key="sk-test",
            model="gpt-4",
            api_format="openai",
        )
        assert config.api_format == "openai"
        assert config.model == "gpt-4"


# --- get_judge_config tests ---


class TestGetJudgeConfig:
    def test_returns_none_when_no_env(self):
        with patch.dict(os.environ, {}, clear=True):
            assert get_judge_config() is None

    def test_reads_env_vars(self):
        env = {
            "FLEET_JUDGE_ENDPOINT": "https://llm.example.com",
            "FLEET_JUDGE_API_KEY": "sk-123",
            "FLEET_JUDGE_MODEL": "gpt-4",
            "FLEET_JUDGE_API_FORMAT": "openai",
        }
        with patch.dict(os.environ, env, clear=True):
            config = get_judge_config()
            assert config is not None
            assert config.url == "https://llm.example.com"
            assert config.api_key == "sk-123"
            assert config.model == "gpt-4"
            assert config.api_format == "openai"

    def test_defaults_when_partial_env(self):
        env = {
            "FLEET_JUDGE_ENDPOINT": "https://llm.example.com",
        }
        with patch.dict(os.environ, env, clear=True):
            config = get_judge_config()
            assert config is not None
            assert config.api_key == ""
            assert config.model == "claude-sonnet-4-20250514"
            assert config.api_format == "anthropic"


# --- JudgeService tests ---


def _make_service(api_format="anthropic"):
    config = JudgeEndpointConfig(
        url="https://api.example.com",
        api_key="sk-test",
        api_format=api_format,
    )
    return JudgeService(config)


def _make_rubric():
    return Rubric(
        criteria=[
            Criterion(
                name="accuracy",
                max_score=5,
                levels={0: "Wrong", 3: "Partial", 5: "Perfect"},
            ),
            Criterion(
                name="style",
                max_score=3,
                levels={0: "Poor", 3: "Excellent"},
            ),
        ],
        task_context="Solve a math problem",
    )


class TestBuildPrompt:
    def test_basic_prompt(self):
        service = _make_service()
        rubric = _make_rubric()
        messages = service._build_prompt(rubric, "The answer is 42.")
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        content = messages[0]["content"]
        assert "## Task Context" in content
        assert "Solve a math problem" in content
        assert "accuracy" in content
        assert "style" in content
        assert "The answer is 42." in content

    def test_with_files(self):
        service = _make_service()
        rubric = _make_rubric()
        messages = service._build_prompt(
            rubric, "submission", files={"main.py": "print('hello')"}
        )
        content = messages[0]["content"]
        assert "## Files" in content
        assert "main.py" in content
        assert "print('hello')" in content

    def test_with_conversation(self):
        service = _make_service()
        rubric = _make_rubric()
        conv = [
            {"role": "user", "content": "Help me"},
            {"role": "assistant", "content": "Sure"},
        ]
        messages = service._build_prompt(rubric, "submission", conversation=conv)
        content = messages[0]["content"]
        assert "## Conversation History" in content
        assert "**user**: Help me" in content
        assert "**assistant**: Sure" in content

    def test_no_task_context(self):
        service = _make_service()
        rubric = Rubric(criteria=[Criterion(name="test", max_score=1)])
        messages = service._build_prompt(rubric, "sub")
        content = messages[0]["content"]
        assert "## Task Context" not in content


class TestParseResponse:
    def test_valid_response(self):
        service = _make_service()
        rubric = _make_rubric()
        raw = json.dumps(
            {
                "scores": {
                    "accuracy": {"score": 4, "reasoning": "Mostly correct"},
                    "style": {"score": 2, "reasoning": "Decent style"},
                }
            }
        )
        result = service._parse_response(raw, rubric)
        assert result.scores["accuracy"] == 4.0
        assert result.scores["style"] == 2.0
        assert result.total == 6.0
        assert result.max_total == 8.0
        assert result.normalized == 0.75
        assert result.reasoning["accuracy"] == "Mostly correct"

    def test_malformed_json(self):
        service = _make_service()
        rubric = _make_rubric()
        result = service._parse_response("not json at all", rubric)
        assert result.scores["accuracy"] == 0.0
        assert result.scores["style"] == 0.0
        assert result.total == 0.0
        assert result.normalized == 0.0

    def test_missing_criterion(self):
        service = _make_service()
        rubric = _make_rubric()
        raw = json.dumps(
            {
                "scores": {
                    "accuracy": {"score": 5, "reasoning": "Perfect"},
                    # style is missing
                }
            }
        )
        result = service._parse_response(raw, rubric)
        assert result.scores["accuracy"] == 5.0
        assert result.scores["style"] == 0.0
        assert result.total == 5.0

    def test_empty_rubric(self):
        service = _make_service()
        rubric = Rubric(criteria=[])
        result = service._parse_response("{}", rubric)
        assert result.total == 0.0
        assert result.max_total == 0.0
        assert result.normalized == 0.0


class TestCallAnthropic:
    def test_request_format(self):
        service = _make_service("anthropic")
        mock_response = Mock()
        mock_response.json.return_value = {
            "content": [{"type": "text", "text": '{"scores": {}}'}]
        }
        mock_response.raise_for_status = Mock()

        with patch.object(service._client, "post", return_value=mock_response) as mock_post:
            result = service._call_anthropic([{"role": "user", "content": "test"}])

            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert call_args[0][0] == "https://api.example.com/v1/messages"
            body = call_args[1]["json"]
            assert body["model"] == "claude-sonnet-4-20250514"
            assert body["max_tokens"] == 4096
            assert body["system"] == _SYSTEM_PROMPT
            assert body["messages"] == [{"role": "user", "content": "test"}]
            headers = call_args[1]["headers"]
            assert headers["x-api-key"] == "sk-test"
            assert result == '{"scores": {}}'

    def test_url_already_has_path(self):
        config = JudgeEndpointConfig(
            url="https://api.example.com/v1/messages",
            api_key="sk-test",
        )
        service = JudgeService(config)
        mock_response = Mock()
        mock_response.json.return_value = {"content": [{"type": "text", "text": "ok"}]}
        mock_response.raise_for_status = Mock()

        with patch.object(service._client, "post", return_value=mock_response) as mock_post:
            service._call_anthropic([{"role": "user", "content": "test"}])
            assert mock_post.call_args[0][0] == "https://api.example.com/v1/messages"


class TestCallOpenAI:
    def test_request_format(self):
        service = _make_service("openai")
        mock_response = Mock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": '{"scores": {}}'}}]
        }
        mock_response.raise_for_status = Mock()

        with patch.object(service._client, "post", return_value=mock_response) as mock_post:
            result = service._call_openai([{"role": "user", "content": "test"}])

            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert call_args[0][0] == "https://api.example.com/v1/chat/completions"
            body = call_args[1]["json"]
            assert body["model"] == "claude-sonnet-4-20250514"
            assert body["messages"][0]["role"] == "system"
            assert body["messages"][0]["content"] == _SYSTEM_PROMPT
            assert body["response_format"] == {"type": "json_object"}
            headers = call_args[1]["headers"]
            assert headers["Authorization"] == "Bearer sk-test"
            assert result == '{"scores": {}}'


class TestGradeEndToEnd:
    def test_anthropic_grade(self):
        service = _make_service("anthropic")
        rubric = _make_rubric()

        llm_response = json.dumps(
            {
                "scores": {
                    "accuracy": {"score": 5, "reasoning": "Perfect"},
                    "style": {"score": 3, "reasoning": "Excellent"},
                }
            }
        )
        mock_response = Mock()
        mock_response.json.return_value = {
            "content": [{"type": "text", "text": llm_response}]
        }
        mock_response.raise_for_status = Mock()

        with patch.object(service._client, "post", return_value=mock_response):
            result = service.grade(rubric, "My submission")

        assert result.scores["accuracy"] == 5.0
        assert result.scores["style"] == 3.0
        assert result.total == 8.0
        assert result.max_total == 8.0
        assert result.normalized == 1.0
        assert result.reasoning["accuracy"] == "Perfect"

    def test_openai_grade(self):
        service = _make_service("openai")
        rubric = _make_rubric()

        llm_response = json.dumps(
            {
                "scores": {
                    "accuracy": {"score": 3, "reasoning": "Partial"},
                    "style": {"score": 1, "reasoning": "OK"},
                }
            }
        )
        mock_response = Mock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": llm_response}}]
        }
        mock_response.raise_for_status = Mock()

        with patch.object(service._client, "post", return_value=mock_response):
            result = service.grade(rubric, "My submission")

        assert result.scores["accuracy"] == 3.0
        assert result.scores["style"] == 1.0
        assert result.total == 4.0
        assert result.normalized == 0.5


# --- SyncEnv.judge property test ---


_MANAGER_URLS = {
    "api": "https://example.com/api/v1/env",
    "docs": "https://example.com/docs",
    "reset": "https://example.com/reset",
    "diff": "https://example.com/diff",
    "snapshot": "https://example.com/snapshot",
    "execute_verifier_function": "https://example.com/execute",
    "execute_verifier_function_with_upload": "https://example.com/execute_upload",
}

_ENV_DATA = {
    "instance_id": "test-id",
    "env_key": "test-env",
    "version": "1",
    "status": "running",
    "subdomain": "test",
    "created_at": "2025-01-01",
    "updated_at": "2025-01-01",
    "team_id": "team-1",
    "region": "us-west-1",
    "urls": {
        "root": "https://example.com/",
        "app": [],
        "manager": _MANAGER_URLS,
    },
}


class TestSyncEnvJudge:
    def test_judge_property_with_config(self):
        config = JudgeEndpointConfig(
            url="https://api.example.com",
            api_key="sk-test",
        )
        from fleet.client import SyncEnv

        env = SyncEnv(client=None, judge_config=config, **_ENV_DATA)
        judge = env.judge
        assert isinstance(judge, JudgeService)
        assert judge.config.url == "https://api.example.com"

    def test_judge_property_from_env_vars(self):
        env_vars = {
            "FLEET_JUDGE_ENDPOINT": "https://judge.example.com",
            "FLEET_JUDGE_API_KEY": "sk-judge",
        }
        from fleet.client import SyncEnv

        with patch.dict(os.environ, env_vars, clear=False):
            env = SyncEnv(client=None, **_ENV_DATA)
            judge = env.judge
            assert isinstance(judge, JudgeService)
            assert judge.config.url == "https://judge.example.com"

    def test_judge_property_raises_without_config(self):
        from fleet.client import SyncEnv
        import fleet as _fleet_mod

        old = getattr(_fleet_mod, "_judge_config", None)
        _fleet_mod._judge_config = None
        try:
            with patch.dict(os.environ, {}, clear=True):
                env = SyncEnv(client=None, **_ENV_DATA)
                with pytest.raises(ValueError, match="No judge configuration found"):
                    _ = env.judge
        finally:
            _fleet_mod._judge_config = old


# --- AsyncJudgeService tests ---


class TestAsyncJudgeService:
    @pytest.mark.asyncio
    async def test_grade(self):
        config = JudgeEndpointConfig(
            url="https://api.example.com",
            api_key="sk-test",
            api_format="anthropic",
        )
        service = AsyncJudgeService(config)
        rubric = _make_rubric()

        llm_response = json.dumps(
            {
                "scores": {
                    "accuracy": {"score": 4, "reasoning": "Good"},
                    "style": {"score": 2, "reasoning": "OK"},
                }
            }
        )
        mock_response = Mock()
        mock_response.json.return_value = {
            "content": [{"type": "text", "text": llm_response}]
        }
        mock_response.raise_for_status = Mock()

        with patch.object(service._client, "post", return_value=mock_response):
            result = await service.grade(rubric, "My submission")

        assert result.scores["accuracy"] == 4.0
        assert result.scores["style"] == 2.0
        assert result.total == 6.0
        assert result.normalized == 0.75


# --- configure() judge params test ---


class TestConfigureJudge:
    def test_configure_sets_judge_config(self):
        import fleet

        old = fleet._judge_config
        try:
            with patch.object(fleet._global_client, "configure"), \
                 patch.object(fleet._async_global_client, "configure"):
                fleet.configure(
                    judge_endpoint="https://judge.test.com",
                    judge_api_key="sk-judge-test",
                    judge_model="gpt-4",
                    judge_api_format="openai",
                )
            config = fleet._judge_config
            assert config is not None
            assert config.url == "https://judge.test.com"
            assert config.api_key == "sk-judge-test"
            assert config.model == "gpt-4"
            assert config.api_format == "openai"
        finally:
            fleet._judge_config = old

    def test_configure_without_judge_leaves_none(self):
        import fleet

        old = fleet._judge_config
        try:
            fleet._judge_config = None
            with patch.object(fleet._global_client, "configure"), \
                 patch.object(fleet._async_global_client, "configure"):
                fleet.configure()
            assert fleet._judge_config is None
        finally:
            fleet._judge_config = old
