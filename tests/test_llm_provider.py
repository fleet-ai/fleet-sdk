"""Tests for the LLM provider abstraction layer (fleet.llm_provider).

Validates:
- FleetProvider delegates to the orchestrator client correctly
- ExternalProvider builds correct OpenAI-compatible requests
- ExternalProvider parses LLM JSON responses into GradeResponse
- SyncJudge routes through LLMProvider when configured
- Backward compatibility: SyncJudge still works without an LLMProvider
"""

import json
from io import StringIO
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from fleet.judge import (
    Criterion,
    JudgeResult,
    Rubric,
    SyncJudge,
    _parse_grade_response,
)
from fleet.llm_provider import (
    ExternalProvider,
    FleetProvider,
    GradeRequest,
    GradeResponse,
    LLMProvider,
    _build_judge_user_message,
    _parse_llm_judge_response,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_rubric() -> Rubric:
    return Rubric(criteria=[
        Criterion(name="Accuracy", max=10, description="How accurate is the answer"),
        Criterion(name="Clarity", max=5, description="How clear is the explanation"),
    ])


def _make_grade_request(rubric=None, submission="The answer is 42.") -> GradeRequest:
    return GradeRequest(
        rubric=rubric or _make_rubric(),
        submission=submission,
        ground_truth="42",
        problem="What is the answer to life?",
        context="This is a philosophy test.",
        instance_id="test-instance-123",
    )


def _mock_orchestrator_response() -> dict:
    """Response shape matching the Fleet orchestrator /v1/judge/grade."""
    return {
        "normalized_score": 0.87,
        "total_score": 13,
        "max_score": 15,
        "model_used": "claude-sonnet-4",
        "provider_used": "anthropic",
        "criteria": [
            {"name": "Accuracy", "score": 8, "max_score": 10, "reasoning": "Correct answer"},
            {"name": "Clarity", "score": 5, "max_score": 5, "reasoning": "Very clear"},
        ],
        "feedback": "Good submission overall.",
    }


def _mock_llm_json_response() -> str:
    """JSON string mimicking what an external LLM returns."""
    return json.dumps({
        "criteria": [
            {"name": "Accuracy", "score": 8, "max_score": 10, "reasoning": "Correct answer"},
            {"name": "Clarity", "score": 5, "max_score": 5, "reasoning": "Very clear"},
        ],
        "feedback": "Good submission overall.",
    })


# ---------------------------------------------------------------------------
# GradeResponse
# ---------------------------------------------------------------------------


class TestGradeResponse:
    def test_to_dict_basic(self):
        resp = GradeResponse(
            normalized_score=0.8,
            total_score=12,
            max_score=15,
            criteria=[{"name": "A", "score": 12, "max_score": 15, "reasoning": "ok"}],
            feedback="Nice",
            model_used="claude-sonnet-4",
            provider_used="openrouter",
        )
        d = resp.to_dict()
        assert d["normalized_score"] == 0.8
        assert d["total_score"] == 12
        assert d["max_score"] == 15
        assert d["model_used"] == "claude-sonnet-4"
        assert d["provider_used"] == "openrouter"
        assert len(d["criteria"]) == 1

    def test_to_dict_empty_criteria_excluded(self):
        resp = GradeResponse(normalized_score=0.5)
        d = resp.to_dict()
        assert "criteria" not in d
        assert "feedback" not in d


# ---------------------------------------------------------------------------
# _build_judge_user_message
# ---------------------------------------------------------------------------


class TestBuildJudgeUserMessage:
    def test_includes_all_sections(self):
        req = _make_grade_request()
        msg = _build_judge_user_message(req)
        assert "## Problem" in msg
        assert "What is the answer to life?" in msg
        assert "## Rubric" in msg
        assert "Accuracy" in msg
        assert "Clarity" in msg
        assert "## Ground Truth" in msg
        assert "42" in msg
        assert "## Additional Context" in msg
        assert "philosophy test" in msg
        assert "## Submission to Grade" in msg
        assert "The answer is 42." in msg

    def test_string_rubric(self):
        req = GradeRequest(rubric="Grade from 1-10", submission="Hello")
        msg = _build_judge_user_message(req)
        assert "Grade from 1-10" in msg

    def test_no_submission(self):
        req = GradeRequest(rubric="Test", submission=None)
        msg = _build_judge_user_message(req)
        assert "No submission text provided" in msg

    def test_conversation_included(self):
        req = GradeRequest(
            rubric="Test",
            submission="Final answer",
            conversation=[
                {"role": "user", "content": "What's 2+2?"},
                {"role": "assistant", "content": "4"},
            ],
        )
        msg = _build_judge_user_message(req)
        assert "Conversation History" in msg
        assert "[user]: What's 2+2?" in msg
        assert "[assistant]: 4" in msg


# ---------------------------------------------------------------------------
# _parse_llm_judge_response
# ---------------------------------------------------------------------------


class TestParseLLMJudgeResponse:
    def test_valid_json(self):
        rubric = _make_rubric()
        resp = _parse_llm_judge_response(
            _mock_llm_json_response(), rubric, "claude-sonnet-4", "openrouter"
        )
        assert resp.normalized_score == pytest.approx(13 / 15, abs=0.01)
        assert resp.total_score == 13
        assert resp.max_score == 15
        assert len(resp.criteria) == 2
        assert resp.feedback == "Good submission overall."
        assert resp.model_used == "claude-sonnet-4"
        assert resp.provider_used == "openrouter"

    def test_json_with_markdown_fences(self):
        raw = f"```json\n{_mock_llm_json_response()}\n```"
        resp = _parse_llm_judge_response(raw, _make_rubric(), "test", "test")
        assert resp.normalized_score > 0

    def test_invalid_json_returns_zero(self):
        resp = _parse_llm_judge_response(
            "This is not JSON", _make_rubric(), "test", "test"
        )
        assert resp.normalized_score == 0.0
        assert "Failed to parse" in resp.feedback

    def test_string_rubric_max_from_criteria(self):
        """When rubric is a plain string, max_score comes from criteria."""
        raw = json.dumps({
            "criteria": [
                {"name": "Quality", "score": 7, "max_score": 10, "reasoning": "Good"},
            ],
            "feedback": "ok",
        })
        resp = _parse_llm_judge_response(raw, "Grade it", "test", "test")
        assert resp.max_score == 10
        assert resp.total_score == 7
        assert resp.normalized_score == pytest.approx(0.7, abs=0.01)


# ---------------------------------------------------------------------------
# FleetProvider
# ---------------------------------------------------------------------------


class TestFleetProvider:
    def test_grade_delegates_to_client(self):
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = _mock_orchestrator_response()
        mock_client.request.return_value = mock_response

        provider = FleetProvider(client=mock_client, instance_id="inst-123")
        req = _make_grade_request()
        resp = provider.grade(req)

        # Verify the client was called
        mock_client.request.assert_called_once()
        call_args = mock_client.request.call_args
        assert call_args[0] == ("POST", "/v1/judge/grade")

        # Verify the response
        assert resp.normalized_score == pytest.approx(0.87, abs=0.01)
        assert len(resp.criteria) == 2
        assert resp.model_used == "claude-sonnet-4"


# ---------------------------------------------------------------------------
# ExternalProvider
# ---------------------------------------------------------------------------


class TestExternalProvider:
    def test_build_request_body(self):
        provider = ExternalProvider(
            api_key="sk-test",
            model="anthropic/claude-sonnet-4",
        )
        req = _make_grade_request()
        body = provider._build_request_body(req)

        assert body["model"] == "anthropic/claude-sonnet-4"
        assert body["temperature"] == 0.0
        assert len(body["messages"]) == 2  # system + user
        assert body["messages"][0]["role"] == "system"
        assert body["messages"][1]["role"] == "user"

    def test_model_override_from_request(self):
        provider = ExternalProvider(
            api_key="sk-test",
            model="default/model",
        )
        req = _make_grade_request()
        req.model = "override/model"
        body = provider._build_request_body(req)
        assert body["model"] == "override/model"

    def test_grade_with_mocked_httpx(self):
        provider = ExternalProvider(
            api_key="sk-test",
            base_url="https://test-api.example.com/v1",
            model="test/model",
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": _mock_llm_json_response(),
                },
            }],
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.Client") as MockClient:
            mock_client_instance = MagicMock()
            mock_client_instance.post.return_value = mock_response
            mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
            mock_client_instance.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_client_instance

            req = _make_grade_request()
            resp = provider.grade(req)

            # Verify API call
            mock_client_instance.post.assert_called_once()
            call_args = mock_client_instance.post.call_args
            assert call_args[0][0] == "https://test-api.example.com/v1/chat/completions"

            # Verify response parsing
            assert resp.normalized_score == pytest.approx(13 / 15, abs=0.01)
            assert len(resp.criteria) == 2
            assert resp.accumulators is not None
            assert "elapsed_ms" in resp.accumulators

    def test_default_base_url(self):
        provider = ExternalProvider(api_key="test")
        assert provider.base_url == "https://openrouter.ai/api/v1"

    def test_custom_headers(self):
        provider = ExternalProvider(
            api_key="test",
            extra_headers={"X-Custom": "value"},
        )
        headers = provider._get_headers()
        assert headers["X-Custom"] == "value"
        assert "Authorization" in headers


# ---------------------------------------------------------------------------
# Custom LLMProvider
# ---------------------------------------------------------------------------


class TestCustomProvider:
    def test_custom_provider_implementation(self):
        """Users can implement their own LLMProvider."""

        class MyProvider(LLMProvider):
            def grade(self, request: GradeRequest) -> GradeResponse:
                return GradeResponse(
                    normalized_score=1.0,
                    total_score=10,
                    max_score=10,
                    criteria=[{"name": "Test", "score": 10, "max_score": 10, "reasoning": "Perfect"}],
                    feedback="Custom provider says: perfect!",
                    model_used="custom-model",
                    provider_used="my-provider",
                )

        provider = MyProvider()
        req = _make_grade_request()
        resp = provider.grade(req)
        assert resp.normalized_score == 1.0
        assert resp.provider_used == "my-provider"


# ---------------------------------------------------------------------------
# SyncJudge integration
# ---------------------------------------------------------------------------


class TestSyncJudgeWithProvider:
    def test_routes_through_llm_provider(self):
        """When llm_provider is set, grade() uses it instead of the client."""

        class StubProvider(LLMProvider):
            def __init__(self):
                self.called = False

            def grade(self, request: GradeRequest) -> GradeResponse:
                self.called = True
                return GradeResponse(
                    normalized_score=0.95,
                    total_score=19,
                    max_score=20,
                    criteria=[
                        {"name": "Accuracy", "score": 10, "max_score": 10, "reasoning": "Spot on"},
                        {"name": "Clarity", "score": 9, "max_score": 10, "reasoning": "Almost perfect"},
                    ],
                    feedback="Excellent work",
                    model_used="stub-model",
                    provider_used="stub",
                )

        stub = StubProvider()
        judge = SyncJudge(client=None, instance_id="local-123", llm_provider=stub)
        result = judge.grade(
            _make_rubric(),
            "The answer is 42.",
            ground_truth="42",
            problem="What is the meaning of life?",
        )

        assert stub.called
        assert isinstance(result, JudgeResult)
        assert float(result) == pytest.approx(0.95, abs=0.01)
        assert result.criteria is not None
        assert len(result.criteria) == 2

    def test_default_routes_through_client(self):
        """Without llm_provider, grade() uses the orchestrator client."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = _mock_orchestrator_response()
        mock_client.request.return_value = mock_response

        judge = SyncJudge(client=mock_client, instance_id="inst-456")
        result = judge.grade(_make_rubric(), "Answer")

        mock_client.request.assert_called_once()
        assert float(result) == pytest.approx(0.87, abs=0.01)

    def test_reference_claims_folded_into_context(self):
        """reference_claims should be folded into context for both paths."""

        class CapturingProvider(LLMProvider):
            def __init__(self):
                self.last_request = None

            def grade(self, request: GradeRequest) -> GradeResponse:
                self.last_request = request
                return GradeResponse(normalized_score=0.5)

        provider = CapturingProvider()
        judge = SyncJudge(client=None, instance_id="local", llm_provider=provider)

        judge.grade(
            "Simple rubric",
            "submission",
            context="Some context",
            reference_claims="Claim 1, Claim 2",
        )

        assert provider.last_request is not None
        assert "Some context" in provider.last_request.context
        assert "Reference Claims" in provider.last_request.context
        assert "Claim 1, Claim 2" in provider.last_request.context


# ---------------------------------------------------------------------------
# End-to-end: ExternalProvider + SyncJudge
# ---------------------------------------------------------------------------


class TestEndToEnd:
    def test_external_provider_with_sync_judge(self):
        """Full integration: ExternalProvider → SyncJudge → JudgeResult."""
        provider = ExternalProvider(
            api_key="sk-test",
            model="test/model",
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{
                "message": {
                    "content": _mock_llm_json_response(),
                },
            }],
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.Client") as MockClient:
            mock_client_instance = MagicMock()
            mock_client_instance.post.return_value = mock_response
            mock_client_instance.__enter__ = MagicMock(return_value=mock_client_instance)
            mock_client_instance.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_client_instance

            judge = SyncJudge(client=None, instance_id="local-e2e", llm_provider=provider)
            result = judge.grade(
                _make_rubric(),
                "The answer is 42.",
                ground_truth="42",
            )

            assert isinstance(result, JudgeResult)
            assert isinstance(result, float)
            assert float(result) > 0
            assert result.criteria is not None
            assert len(result.criteria) == 2
