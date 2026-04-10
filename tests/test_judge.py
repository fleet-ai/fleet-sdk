"""Tests for fleet.judge module."""

from __future__ import annotations

import json
from typing import Any, Dict
from unittest.mock import MagicMock, patch, AsyncMock

import httpx
import pytest

from fleet.judge import (
    AsyncJudge,
    Criterion,
    CriterionScore,
    Judge,
    JudgeEndpointConfig,
    JudgeResult,
    Rubric,
    _build_judge_prompt,
    _get_judge_config,
    _parse_judge_response,
    _set_judge_config,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_criterion():
    return Criterion(name="accuracy", max=3, levels={0: "Wrong", 1: "Partial", 2: "Mostly correct", 3: "Perfect"})


@pytest.fixture
def sample_rubric(sample_criterion):
    return Rubric(
        criteria=[
            sample_criterion,
            Criterion(name="clarity", max=2, levels={0: "Unclear", 1: "Okay", 2: "Clear"}),
        ],
        context="Evaluate a code review submission",
        instructions="Be strict on accuracy.",
    )


@pytest.fixture
def sample_judge_response():
    return json.dumps({
        "scores": [
            {"name": "accuracy", "score": 2, "max_score": 3, "reasoning": "Mostly correct but missed edge case"},
            {"name": "clarity", "score": 2, "max_score": 2, "reasoning": "Well written"},
        ],
        "reasoning": "Good submission overall.",
    })


@pytest.fixture
def anthropic_config():
    return JudgeEndpointConfig(
        url="https://llm.example.com",
        api_key="sk-test-key",
        model="claude-sonnet-4-20250514",
        api_format="anthropic",
    )


@pytest.fixture
def openai_config():
    return JudgeEndpointConfig(
        url="https://llm.example.com",
        api_key="sk-test-key",
        model="gpt-4",
        api_format="openai",
    )


# ---------------------------------------------------------------------------
# Model construction tests
# ---------------------------------------------------------------------------


class TestCriterion:
    def test_basic_construction(self):
        c = Criterion(name="test", max=5, levels={0: "Bad", 5: "Great"})
        assert c.name == "test"
        assert c.max_score == 5
        assert c.levels == {0: "Bad", 5: "Great"}

    def test_max_alias(self):
        c = Criterion(name="x", max=10, levels={0: "Low", 10: "High"})
        assert c.max_score == 10


class TestRubric:
    def test_construction(self, sample_criterion):
        r = Rubric(
            criteria=[sample_criterion],
            context="Some context",
            instructions="Be fair",
        )
        assert len(r.criteria) == 1
        assert r.context == "Some context"
        assert r.instructions == "Be fair"

    def test_optional_fields(self, sample_criterion):
        r = Rubric(criteria=[sample_criterion])
        assert r.context is None
        assert r.instructions is None


class TestJudgeEndpointConfig:
    def test_defaults(self):
        cfg = JudgeEndpointConfig(url="https://api.example.com", api_key="key")
        assert cfg.model == "claude-sonnet-4-20250514"
        assert cfg.api_format == "anthropic"

    def test_openai_format(self):
        cfg = JudgeEndpointConfig(
            url="https://api.example.com",
            api_key="key",
            model="gpt-4",
            api_format="openai",
        )
        assert cfg.api_format == "openai"
        assert cfg.model == "gpt-4"

    def test_validation_requires_url(self):
        with pytest.raises(Exception):
            JudgeEndpointConfig(api_key="key")  # type: ignore[call-arg]


class TestJudgeResult:
    def test_float_conversion(self):
        result = JudgeResult(
            scores=[
                CriterionScore(name="a", score=3, max_score=5, reasoning="ok"),
            ],
            total_score=0.6,
            raw_total=3,
            max_total=5,
            reasoning="decent",
        )
        assert float(result) == 0.6

    def test_total_score_normalized(self):
        result = JudgeResult(
            scores=[], total_score=0.0, raw_total=0, max_total=0, reasoning=""
        )
        assert float(result) == 0.0


# ---------------------------------------------------------------------------
# Prompt construction tests
# ---------------------------------------------------------------------------


class TestBuildJudgePrompt:
    def test_basic_prompt(self, sample_rubric):
        system, messages = _build_judge_prompt(sample_rubric, submission="Hello world")
        assert "expert judge" in system.lower()
        assert len(messages) == 1
        assert messages[0]["role"] == "user"
        content = messages[0]["content"]
        assert "accuracy" in content
        assert "clarity" in content
        assert "Hello world" in content

    def test_context_included(self, sample_rubric):
        _, messages = _build_judge_prompt(sample_rubric, submission="test")
        content = messages[0]["content"]
        assert "Evaluate a code review submission" in content

    def test_instructions_included(self, sample_rubric):
        _, messages = _build_judge_prompt(sample_rubric, submission="test")
        content = messages[0]["content"]
        assert "Be strict on accuracy" in content

    def test_conversation_included(self, sample_rubric):
        _, messages = _build_judge_prompt(
            sample_rubric, conversation="User: hi\nAssistant: hello"
        )
        content = messages[0]["content"]
        assert "User: hi" in content
        assert "## Conversation" in content

    def test_files_included(self, sample_rubric):
        _, messages = _build_judge_prompt(
            sample_rubric, files={"main.py": "print('hello')"}
        )
        content = messages[0]["content"]
        assert "main.py" in content
        assert "print('hello')" in content

    def test_final_answer_included(self, sample_rubric):
        _, messages = _build_judge_prompt(
            sample_rubric, final_answer="42"
        )
        content = messages[0]["content"]
        assert "## Final Answer" in content
        assert "42" in content

    def test_no_submission_or_files(self, sample_rubric):
        system, messages = _build_judge_prompt(sample_rubric)
        assert len(messages) == 1
        assert "## Rubric" in messages[0]["content"]


# ---------------------------------------------------------------------------
# Response parsing tests
# ---------------------------------------------------------------------------


class TestParseJudgeResponse:
    def test_valid_json(self, sample_rubric, sample_judge_response):
        result = _parse_judge_response(sample_judge_response, sample_rubric)
        assert isinstance(result, JudgeResult)
        assert len(result.scores) == 2
        assert result.raw_total == 4
        assert result.max_total == 5
        assert result.total_score == pytest.approx(0.8)
        assert result.reasoning == "Good submission overall."

    def test_json_in_code_fence(self, sample_rubric):
        text = '```json\n{"scores": [{"name": "accuracy", "score": 3, "max_score": 3, "reasoning": "perfect"}], "reasoning": "great"}\n```'
        result = _parse_judge_response(text, sample_rubric)
        assert len(result.scores) == 1
        assert result.scores[0].score == 3

    def test_max_score_from_rubric(self, sample_rubric, sample_judge_response):
        result = _parse_judge_response(sample_judge_response, sample_rubric)
        accuracy_score = next(s for s in result.scores if s.name == "accuracy")
        assert accuracy_score.max_score == 3  # from rubric, not response

    def test_invalid_json_raises(self, sample_rubric):
        with pytest.raises(json.JSONDecodeError):
            _parse_judge_response("not json at all", sample_rubric)

    def test_zero_max_total(self):
        rubric = Rubric(criteria=[])
        response = json.dumps({"scores": [], "reasoning": "empty"})
        result = _parse_judge_response(response, rubric)
        assert result.total_score == 0.0
        assert result.max_total == 0


# ---------------------------------------------------------------------------
# Judge.grade() with mock endpoints
# ---------------------------------------------------------------------------


class TestJudgeGradeAnthropic:
    def test_grade_anthropic(self, anthropic_config, sample_rubric, sample_judge_response):
        judge = Judge(endpoint_config=anthropic_config)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "content": [{"type": "text", "text": sample_judge_response}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("fleet.judge.httpx.post", return_value=mock_response) as mock_post:
            result = judge.grade(rubric=sample_rubric, submission="test answer")

        assert isinstance(result, JudgeResult)
        assert result.total_score == pytest.approx(0.8)
        assert float(result) == pytest.approx(0.8)

        # Verify correct endpoint called
        call_args = mock_post.call_args
        assert "/v1/messages" in call_args[0][0]
        assert call_args[1]["headers"]["x-api-key"] == "sk-test-key"

    def test_grade_anthropic_url_trailing_slash(self, sample_rubric, sample_judge_response):
        config = JudgeEndpointConfig(
            url="https://llm.example.com/",
            api_key="key",
        )
        judge = Judge(endpoint_config=config)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "content": [{"type": "text", "text": sample_judge_response}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("fleet.judge.httpx.post", return_value=mock_response) as mock_post:
            judge.grade(rubric=sample_rubric, submission="test")

        url_called = mock_post.call_args[0][0]
        assert url_called == "https://llm.example.com/v1/messages"


class TestJudgeGradeOpenAI:
    def test_grade_openai(self, openai_config, sample_rubric, sample_judge_response):
        judge = Judge(endpoint_config=openai_config)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "choices": [{"message": {"content": sample_judge_response}}]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("fleet.judge.httpx.post", return_value=mock_response) as mock_post:
            result = judge.grade(rubric=sample_rubric, submission="test answer")

        assert isinstance(result, JudgeResult)
        assert result.total_score == pytest.approx(0.8)

        call_args = mock_post.call_args
        assert "/v1/chat/completions" in call_args[0][0]
        assert call_args[1]["headers"]["Authorization"] == "Bearer sk-test-key"
        payload = call_args[1]["json"]
        assert payload["response_format"] == {"type": "json_object"}


class TestJudgeGradeOrchestrator:
    def test_grade_orchestrator_fallback(self, sample_rubric, sample_judge_response):
        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"response": sample_judge_response}
        mock_resp.text = sample_judge_response
        mock_client.request.return_value = mock_resp

        judge = Judge(orchestrator_client=mock_client, instance_id="inst-123")
        result = judge.grade(rubric=sample_rubric, submission="answer")

        assert isinstance(result, JudgeResult)
        mock_client.request.assert_called_once()
        call_args = mock_client.request.call_args
        assert call_args[0] == ("POST", "/v1/judge/grade")

    def test_grade_no_config_no_client_raises(self, sample_rubric):
        judge = Judge()
        with pytest.raises(ValueError, match="No judge endpoint configured"):
            judge.grade(rubric=sample_rubric, submission="test")


# ---------------------------------------------------------------------------
# AsyncJudge.grade() tests
# ---------------------------------------------------------------------------


class TestAsyncJudgeGrade:
    @pytest.mark.asyncio
    async def test_grade_anthropic_async(self, anthropic_config, sample_rubric, sample_judge_response):
        judge = AsyncJudge(endpoint_config=anthropic_config)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "content": [{"type": "text", "text": sample_judge_response}]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client_instance = AsyncMock()
        mock_client_instance.post.return_value = mock_response
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)

        with patch("fleet.judge.httpx.AsyncClient", return_value=mock_client_instance):
            result = await judge.grade(rubric=sample_rubric, submission="test")

        assert isinstance(result, JudgeResult)
        assert result.total_score == pytest.approx(0.8)

    @pytest.mark.asyncio
    async def test_grade_openai_async(self, openai_config, sample_rubric, sample_judge_response):
        judge = AsyncJudge(endpoint_config=openai_config)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": sample_judge_response}}]
        }
        mock_response.raise_for_status = MagicMock()

        mock_client_instance = AsyncMock()
        mock_client_instance.post.return_value = mock_response
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=False)

        with patch("fleet.judge.httpx.AsyncClient", return_value=mock_client_instance):
            result = await judge.grade(rubric=sample_rubric, submission="test")

        assert isinstance(result, JudgeResult)

    @pytest.mark.asyncio
    async def test_grade_no_config_no_client_raises_async(self, sample_rubric):
        judge = AsyncJudge()
        with pytest.raises(ValueError, match="No judge endpoint configured"):
            await judge.grade(rubric=sample_rubric, submission="test")


# ---------------------------------------------------------------------------
# Global config tests
# ---------------------------------------------------------------------------


class TestGlobalJudgeConfig:
    def test_get_set_config(self):
        _set_judge_config(None)
        assert _get_judge_config() is None

        cfg = JudgeEndpointConfig(url="https://x.com", api_key="k")
        _set_judge_config(cfg)
        assert _get_judge_config() is cfg

        # Cleanup
        _set_judge_config(None)

    def test_configure_sets_judge_config(self):
        import fleet
        from fleet.judge import _get_judge_config, _set_judge_config

        _set_judge_config(None)

        # Mock the global client configure calls since they require real API keys
        with patch.object(fleet._global_client, "configure"), \
             patch.object(fleet._async_global_client, "configure"):
            fleet.configure(
                api_key="test-fleet-key",
                judge_endpoint="https://judge.example.com",
                judge_api_key="sk-judge",
                judge_model="claude-sonnet-4-20250514",
                judge_api_format="openai",
            )

        cfg = _get_judge_config()
        assert cfg is not None
        assert cfg.url == "https://judge.example.com"
        assert cfg.api_key == "sk-judge"
        assert cfg.model == "claude-sonnet-4-20250514"
        assert cfg.api_format == "openai"

        # Cleanup
        _set_judge_config(None)


# ---------------------------------------------------------------------------
# Import tests
# ---------------------------------------------------------------------------


class TestImports:
    def test_import_from_fleet_judge(self):
        from fleet.judge import Rubric, Criterion, Judge, JudgeResult
        assert Rubric is not None
        assert Criterion is not None
        assert Judge is not None
        assert JudgeResult is not None

    def test_import_from_fleet(self):
        from fleet import Rubric, Criterion, Judge, JudgeResult, CriterionScore, JudgeEndpointConfig
        assert Rubric is not None
        assert Criterion is not None
        assert Judge is not None
        assert JudgeResult is not None
        assert CriterionScore is not None
        assert JudgeEndpointConfig is not None

    def test_import_async_judge(self):
        from fleet.judge import AsyncJudge
        from fleet import AsyncJudge as AJ
        assert AsyncJudge is AJ
