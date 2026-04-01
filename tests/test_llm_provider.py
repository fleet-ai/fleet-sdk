"""Tests for the LLM provider abstraction layer (fleet.llm_provider).

Validates:
- FleetProvider delegates to the orchestrator client correctly
- ExternalProvider builds correct OpenAI-compatible requests
- ExternalProvider parses LLM JSON responses into GradeResponse
- SyncJudge routes through LLMProvider when configured
- Backward compatibility: SyncJudge still works without an LLMProvider
- resolve_provider() reads env vars and builds ExternalProvider
- Image.from_local / File.from_local read from local filesystem
"""

import base64
import json
import os
import tempfile
from typing import Any, Dict, Optional
from unittest.mock import MagicMock, patch, AsyncMock

import httpx
import pytest

from fleet.judge import (
    Criterion,
    File,
    Image,
    JudgeResult,
    Rubric,
    SyncJudge,
    _parse_grade_response,
)
from fleet.llm_provider import (
    ENV_LLM_API_KEY,
    ENV_LLM_BASE_URL,
    ENV_LLM_MODEL,
    ENV_LLM_MAX_TOKENS,
    ENV_LLM_TEMPERATURE,
    ENV_LLM_TIMEOUT,
    ExternalProvider,
    FleetProvider,
    GradeRequest,
    GradeResponse,
    LLMProvider,
    resolve_provider,
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


def _clean_llm_env(monkeypatch):
    """Remove all FLEET_LLM_* env vars for a clean test."""
    for var in [ENV_LLM_API_KEY, ENV_LLM_BASE_URL, ENV_LLM_MODEL,
                ENV_LLM_TEMPERATURE, ENV_LLM_MAX_TOKENS, ENV_LLM_TIMEOUT]:
        monkeypatch.delenv(var, raising=False)


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
# resolve_provider() — env var auto-configuration
# ---------------------------------------------------------------------------


class TestResolveProvider:
    def test_returns_none_when_no_api_key(self, monkeypatch):
        """Without FLEET_LLM_API_KEY, resolve_provider returns None."""
        _clean_llm_env(monkeypatch)
        assert resolve_provider() is None

    def test_returns_external_provider_with_api_key(self, monkeypatch):
        """With FLEET_LLM_API_KEY set, returns ExternalProvider."""
        _clean_llm_env(monkeypatch)
        monkeypatch.setenv(ENV_LLM_API_KEY, "sk-test-key-123")
        provider = resolve_provider()
        assert isinstance(provider, ExternalProvider)
        assert provider.api_key == "sk-test-key-123"
        # Defaults
        assert provider.base_url == "https://openrouter.ai/api/v1"
        assert provider.model == "anthropic/claude-sonnet-4"
        assert provider.temperature == 0.0
        assert provider.max_tokens == 4096

    def test_all_env_vars_respected(self, monkeypatch):
        """All FLEET_LLM_* env vars are picked up."""
        _clean_llm_env(monkeypatch)
        monkeypatch.setenv(ENV_LLM_API_KEY, "sk-custom")
        monkeypatch.setenv(ENV_LLM_BASE_URL, "https://my-llm.example.com/v1")
        monkeypatch.setenv(ENV_LLM_MODEL, "my-org/my-model")
        monkeypatch.setenv(ENV_LLM_TEMPERATURE, "0.7")
        monkeypatch.setenv(ENV_LLM_MAX_TOKENS, "8192")
        monkeypatch.setenv(ENV_LLM_TIMEOUT, "600")

        provider = resolve_provider()
        assert isinstance(provider, ExternalProvider)
        assert provider.api_key == "sk-custom"
        assert provider.base_url == "https://my-llm.example.com/v1"
        assert provider.model == "my-org/my-model"
        assert provider.temperature == pytest.approx(0.7)
        assert provider.max_tokens == 8192
        assert provider.timeout == pytest.approx(600.0)

    def test_invalid_temperature_uses_default(self, monkeypatch):
        _clean_llm_env(monkeypatch)
        monkeypatch.setenv(ENV_LLM_API_KEY, "sk-test")
        monkeypatch.setenv(ENV_LLM_TEMPERATURE, "not-a-number")
        provider = resolve_provider()
        assert provider.temperature == 0.0

    def test_invalid_max_tokens_uses_default(self, monkeypatch):
        _clean_llm_env(monkeypatch)
        monkeypatch.setenv(ENV_LLM_API_KEY, "sk-test")
        monkeypatch.setenv(ENV_LLM_MAX_TOKENS, "banana")
        provider = resolve_provider()
        assert provider.max_tokens == 4096


# ---------------------------------------------------------------------------
# SyncJudge auto-resolve from env vars
# ---------------------------------------------------------------------------


class TestSyncJudgeEnvAutoResolve:
    def test_auto_resolves_from_env(self, monkeypatch):
        """SyncJudge auto-detects FLEET_LLM_API_KEY and routes externally."""
        _clean_llm_env(monkeypatch)
        monkeypatch.setenv(ENV_LLM_API_KEY, "sk-auto-test")
        monkeypatch.setenv(ENV_LLM_MODEL, "test/auto-model")

        judge = SyncJudge(client=None, instance_id="auto-test")
        assert judge._llm_provider is not None
        assert isinstance(judge._llm_provider, ExternalProvider)
        assert judge._llm_provider.model == "test/auto-model"

    def test_defaults_to_fleet_when_no_env(self, monkeypatch):
        """Without env vars, SyncJudge._llm_provider is None (Fleet route)."""
        _clean_llm_env(monkeypatch)
        mock_client = MagicMock()
        judge = SyncJudge(client=mock_client, instance_id="fleet-test")
        assert judge._llm_provider is None

    def test_explicit_provider_overrides_env(self, monkeypatch):
        """Explicit llm_provider kwarg takes priority over env vars."""
        _clean_llm_env(monkeypatch)
        monkeypatch.setenv(ENV_LLM_API_KEY, "sk-from-env")

        class CustomProv(LLMProvider):
            def grade(self, request):
                return GradeResponse(normalized_score=0.42)

        custom = CustomProv()
        judge = SyncJudge(client=None, instance_id="test", llm_provider=custom)
        assert judge._llm_provider is custom

    def test_explicit_none_disables_env_auto(self, monkeypatch):
        """Passing llm_provider=None explicitly skips env auto-detect."""
        _clean_llm_env(monkeypatch)
        monkeypatch.setenv(ENV_LLM_API_KEY, "sk-should-be-ignored")

        mock_client = MagicMock()
        judge = SyncJudge(client=mock_client, instance_id="test", llm_provider=None)
        assert judge._llm_provider is None


# ---------------------------------------------------------------------------
# SyncJudge integration (from earlier tests)
# ---------------------------------------------------------------------------


class TestSyncJudgeWithProvider:
    def test_routes_through_llm_provider(self, monkeypatch):
        """When llm_provider is set, grade() uses it instead of the client."""
        _clean_llm_env(monkeypatch)

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

    def test_default_routes_through_client(self, monkeypatch):
        """Without llm_provider, grade() uses the orchestrator client."""
        _clean_llm_env(monkeypatch)
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.json.return_value = _mock_orchestrator_response()
        mock_client.request.return_value = mock_response

        judge = SyncJudge(client=mock_client, instance_id="inst-456")
        result = judge.grade(_make_rubric(), "Answer")

        mock_client.request.assert_called_once()
        assert float(result) == pytest.approx(0.87, abs=0.01)

    def test_reference_claims_folded_into_context(self, monkeypatch):
        """reference_claims should be folded into context for both paths."""
        _clean_llm_env(monkeypatch)

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
# Image.from_local / File.from_local
# ---------------------------------------------------------------------------


class TestImageFromLocal:
    def test_from_local_creates_local_source(self):
        img = Image.from_local("/tmp/test.png")
        assert img.source == "local"
        assert img._local_path == "/tmp/test.png"
        assert img.filename == "test.png"
        assert img.media_type == "image/png"

    def test_from_local_serializes_to_base64(self):
        """from_local reads the file and serializes as base64."""
        raw_bytes = b"\x89PNG\r\n\x1a\nfake-png-content"
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(raw_bytes)
            path = f.name
        try:
            img = Image.from_local(path)
            d = img.serialize()
            assert d["source"] == "base64"
            assert d["media_type"] == "image/png"
            # Verify the data decodes back to original bytes
            assert base64.b64decode(d["data"]) == raw_bytes
        finally:
            os.unlink(path)

    def test_from_local_raises_on_missing_file(self):
        img = Image.from_local("/tmp/nonexistent_image_12345.png")
        with pytest.raises(ValueError, match="Cannot read local image"):
            img.serialize()

    def test_from_local_media_type_override(self):
        img = Image.from_local("/tmp/photo.webp", media_type="image/webp")
        assert img.media_type == "image/webp"

    def test_from_local_guesses_jpeg(self):
        img = Image.from_local("/tmp/photo.jpg")
        assert img.media_type == "image/jpeg"

    def test_s3_still_works(self):
        """Ensure S3 constructor is not broken."""
        img = Image.s3("s3://bucket/key.png", media_type="image/png")
        assert img.source == "s3"
        d = img.serialize()
        assert d["source"] == "s3"
        assert d["url"] == "s3://bucket/key.png"

    def test_from_url_still_works(self):
        """Ensure URL constructor is not broken."""
        img = Image.from_url("https://example.com/img.png")
        assert img.source == "url"
        d = img.serialize()
        assert d["source"] == "url"
        assert d["url"] == "https://example.com/img.png"


class TestFileFromLocal:
    def test_from_local_creates_local_source(self):
        f = File.from_local("/tmp/report.pdf")
        assert f.source == "local"
        assert f._local_path == "/tmp/report.pdf"
        assert f.filename == "report.pdf"
        assert f.media_type == "application/pdf"

    def test_from_local_serializes_to_base64(self):
        raw_bytes = b"%PDF-1.4 fake pdf content"
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
            tf.write(raw_bytes)
            path = tf.name
        try:
            f = File.from_local(path)
            d = f.serialize()
            assert d["source"] == "base64"
            assert d["media_type"] == "application/pdf"
            assert d["filename"] == os.path.basename(path)
            assert base64.b64decode(d["data"]) == raw_bytes
        finally:
            os.unlink(path)

    def test_from_local_raises_on_missing_file(self):
        f = File.from_local("/tmp/nonexistent_file_12345.pdf")
        with pytest.raises(ValueError, match="Cannot read local file"):
            f.serialize()

    def test_from_local_csv(self):
        raw_bytes = b"name,value\nalice,42\n"
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tf:
            tf.write(raw_bytes)
            path = tf.name
        try:
            f = File.from_local(path)
            assert f.media_type == "text/csv"
            d = f.serialize()
            assert base64.b64decode(d["data"]) == raw_bytes
        finally:
            os.unlink(path)

    def test_s3_still_works(self):
        """Ensure S3 constructor is not broken."""
        f = File.s3("s3://bucket/data.csv", media_type="text/csv")
        assert f.source == "s3"
        d = f.serialize()
        assert d["source"] == "s3"
        assert d["url"] == "s3://bucket/data.csv"


# ---------------------------------------------------------------------------
# ExternalProvider with local images
# ---------------------------------------------------------------------------


class TestExternalProviderLocalImages:
    def test_local_image_resolved_in_request_body(self):
        """Local images are resolved to base64 in the LLM request body."""
        raw_bytes = b"\x89PNG\r\n\x1a\nfake-png"
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(raw_bytes)
            path = f.name
        try:
            provider = ExternalProvider(api_key="sk-test", model="test/model")
            img = Image.from_local(path)
            req = GradeRequest(
                rubric="Test rubric",
                submission="Answer",
                images={"screenshot": img},
            )
            body = provider._build_request_body(req)

            # The user message should contain an image_url block with data: URI
            user_msg = body["messages"][1]
            content_blocks = user_msg["content"]
            image_blocks = [b for b in content_blocks if b.get("type") == "image_url"]
            assert len(image_blocks) == 1
            assert image_blocks[0]["image_url"]["url"].startswith("data:image/png;base64,")
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# End-to-end: ExternalProvider + SyncJudge
# ---------------------------------------------------------------------------


class TestEndToEnd:
    def test_external_provider_with_sync_judge(self, monkeypatch):
        """Full integration: ExternalProvider → SyncJudge → JudgeResult."""
        _clean_llm_env(monkeypatch)
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

    def test_env_var_auto_config_e2e(self, monkeypatch):
        """Full e2e: env vars → auto ExternalProvider → SyncJudge → JudgeResult."""
        _clean_llm_env(monkeypatch)
        monkeypatch.setenv(ENV_LLM_API_KEY, "sk-auto-e2e")
        monkeypatch.setenv(ENV_LLM_BASE_URL, "https://e2e-api.example.com/v1")
        monkeypatch.setenv(ENV_LLM_MODEL, "test/e2e-model")

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

            # No explicit provider — should auto-detect from env
            judge = SyncJudge(client=None, instance_id="env-e2e")
            assert isinstance(judge._llm_provider, ExternalProvider)

            result = judge.grade(_make_rubric(), "The answer is 42.")

            # Verify it called the right URL
            call_args = mock_client_instance.post.call_args
            assert call_args[0][0] == "https://e2e-api.example.com/v1/chat/completions"

            assert isinstance(result, JudgeResult)
            assert float(result) > 0


# ---------------------------------------------------------------------------
# Image.from_path — source-agnostic constructor
# ---------------------------------------------------------------------------


class TestImageFromPath:
    def test_creates_path_source(self):
        img = Image.from_path("screenshots/gold.png")
        assert img.source == "path"
        assert img._path == "screenshots/gold.png"
        assert img.filename == "gold.png"
        assert img.media_type == "image/png"

    def test_s3_uri(self):
        img = Image.from_path("s3://bucket/screenshots/gold.png")
        assert img.source == "path"
        assert img._path == "s3://bucket/screenshots/gold.png"

    def test_http_url(self):
        img = Image.from_path("https://example.com/gold.png")
        assert img.source == "path"
        assert img._path == "https://example.com/gold.png"

    def test_absolute_local(self):
        img = Image.from_path("/data/images/gold.png")
        assert img.source == "path"
        assert img._path == "/data/images/gold.png"

    def test_media_type_override(self):
        img = Image.from_path("image.webp", media_type="image/webp")
        assert img.media_type == "image/webp"

    def test_serialize_s3_fallback(self):
        """When no provider resolves, serialize auto-detects s3:// scheme."""
        img = Image.from_path("s3://bucket/key.png")
        d = img.serialize()
        assert d["source"] == "s3"
        assert d["url"] == "s3://bucket/key.png"

    def test_serialize_http_fallback(self):
        """When no provider resolves, serialize auto-detects https:// scheme."""
        img = Image.from_path("https://example.com/img.png")
        d = img.serialize()
        assert d["source"] == "url"
        assert d["url"] == "https://example.com/img.png"

    def test_serialize_local_fallback(self):
        """When no provider resolves, serialize reads local file."""
        raw_bytes = b"\x89PNG\r\n\x1a\nfake-png-content"
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(raw_bytes)
            path = f.name
        try:
            img = Image.from_path(path)
            d = img.serialize()
            assert d["source"] == "base64"
            assert d["media_type"] == "image/png"
            assert base64.b64decode(d["data"]) == raw_bytes
        finally:
            os.unlink(path)

    def test_serialize_missing_local_raises(self):
        img = Image.from_path("/nonexistent/path/img.png")
        with pytest.raises(ValueError, match="Cannot read image path"):
            img.serialize()


# ---------------------------------------------------------------------------
# File.from_path — source-agnostic constructor
# ---------------------------------------------------------------------------


class TestFileFromPath:
    def test_creates_path_source(self):
        f = File.from_path("reports/output.pdf")
        assert f.source == "path"
        assert f._path == "reports/output.pdf"
        assert f.filename == "output.pdf"
        assert f.media_type == "application/pdf"

    def test_s3_uri(self):
        f = File.from_path("s3://bucket/data.csv")
        assert f.source == "path"
        assert f._path == "s3://bucket/data.csv"

    def test_serialize_s3_fallback(self):
        f = File.from_path("s3://bucket/data.csv")
        d = f.serialize()
        assert d["source"] == "s3"
        assert d["url"] == "s3://bucket/data.csv"

    def test_serialize_local_fallback(self):
        raw_bytes = b"name,value\nalice,42\n"
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tf:
            tf.write(raw_bytes)
            path = tf.name
        try:
            f = File.from_path(path)
            d = f.serialize()
            assert d["source"] == "base64"
            assert d["media_type"] == "text/csv"
            assert base64.b64decode(d["data"]) == raw_bytes
        finally:
            os.unlink(path)

    def test_serialize_missing_local_raises(self):
        f = File.from_path("/nonexistent/path/file.pdf")
        with pytest.raises(ValueError, match="Cannot read file path"):
            f.serialize()


# ---------------------------------------------------------------------------
# LLMProvider.resolve_image / resolve_file
# ---------------------------------------------------------------------------


class TestProviderResolve:
    def test_resolve_image_s3(self):
        """resolve_image converts s3:// path to Image.s3()."""
        provider = ExternalProvider(api_key="sk-test")
        img = Image.from_path("s3://bucket/key.png")
        resolved = provider.resolve_image(img)
        assert resolved.source == "s3"
        assert resolved.url == "s3://bucket/key.png"

    def test_resolve_image_http(self):
        """resolve_image converts https:// path to Image.from_url()."""
        provider = ExternalProvider(api_key="sk-test")
        img = Image.from_path("https://example.com/img.png")
        resolved = provider.resolve_image(img)
        assert resolved.source == "url"
        assert resolved.url == "https://example.com/img.png"

    def test_resolve_image_local(self):
        """resolve_image converts bare path to Image.from_local()."""
        provider = ExternalProvider(api_key="sk-test")
        img = Image.from_path("/data/images/gold.png")
        resolved = provider.resolve_image(img)
        assert resolved.source == "local"
        assert resolved._local_path == "/data/images/gold.png"

    def test_resolve_image_noop_for_non_path(self):
        """resolve_image passes through non-path images unchanged."""
        provider = ExternalProvider(api_key="sk-test")
        img = Image.s3("s3://bucket/key.png")
        resolved = provider.resolve_image(img)
        assert resolved is img  # same object

    def test_resolve_file_s3(self):
        provider = ExternalProvider(api_key="sk-test")
        f = File.from_path("s3://bucket/data.csv")
        resolved = provider.resolve_file(f)
        assert resolved.source == "s3"
        assert resolved.url == "s3://bucket/data.csv"

    def test_resolve_file_local(self):
        provider = ExternalProvider(api_key="sk-test")
        f = File.from_path("/data/reports/output.pdf")
        resolved = provider.resolve_file(f)
        assert resolved.source == "local"
        assert resolved._local_path == "/data/reports/output.pdf"

    def test_resolve_images_dict(self):
        provider = ExternalProvider(api_key="sk-test")
        images = {
            "gold": Image.from_path("s3://bucket/gold.png"),
            "agent": Image.from_path("/local/agent.png"),
            "ref": Image.s3("s3://bucket/ref.png"),  # non-path, should pass through
        }
        resolved = provider.resolve_images(images)
        assert resolved["gold"].source == "s3"
        assert resolved["agent"].source == "local"
        assert resolved["ref"].source == "s3"
        assert resolved["ref"] is images["ref"]  # unchanged

    def test_resolve_images_none(self):
        provider = ExternalProvider(api_key="sk-test")
        assert provider.resolve_images(None) is None

    def test_resolve_files_dict(self):
        provider = ExternalProvider(api_key="sk-test")
        files = {
            "report": File.from_path("s3://bucket/report.pdf"),
            "local": File.from_path("/data/local.csv"),
        }
        resolved = provider.resolve_files(files)
        assert resolved["report"].source == "s3"
        assert resolved["local"].source == "local"


# ---------------------------------------------------------------------------
# Custom provider with resolve override
# ---------------------------------------------------------------------------


class TestCustomProviderResolve:
    def test_custom_resolve_prepends_s3_prefix(self, monkeypatch):
        """Custom provider can override resolve to prepend S3 prefix."""
        _clean_llm_env(monkeypatch)

        class S3PrefixProvider(LLMProvider):
            """Provider that prepends an S3 bucket prefix to bare paths."""

            def __init__(self, bucket: str):
                self.bucket = bucket

            def resolve_image(self, image):
                if getattr(image, "source", None) != "path":
                    return image
                path = image._path or image.filename or ""
                if not path.startswith(("s3://", "http://", "https://")):
                    # Prepend S3 bucket prefix
                    s3_url = f"s3://{self.bucket}/{path}"
                    return Image.s3(s3_url, media_type=image.media_type)
                return super().resolve_image(image)

            def grade(self, request):
                return GradeResponse(normalized_score=1.0)

        provider = S3PrefixProvider(bucket="my-images-bucket")

        # Bare path → gets s3 prefix
        img = Image.from_path("screenshots/gold.png")
        resolved = provider.resolve_image(img)
        assert resolved.source == "s3"
        assert resolved.url == "s3://my-images-bucket/screenshots/gold.png"

        # Already has s3:// → passed through normally
        img2 = Image.from_path("s3://other-bucket/img.png")
        resolved2 = provider.resolve_image(img2)
        assert resolved2.source == "s3"
        assert resolved2.url == "s3://other-bucket/img.png"

    def test_judge_calls_resolve_before_grade(self, monkeypatch):
        """SyncJudge calls provider.resolve_images before grade."""
        _clean_llm_env(monkeypatch)

        class TrackingProvider(LLMProvider):
            def __init__(self):
                self.resolved_images = None

            def resolve_image(self, image):
                if getattr(image, "source", None) != "path":
                    return image
                # Convert all paths to base64 with marker data
                return Image.from_base64("RESOLVED", image.filename or "img.png")

            def grade(self, request):
                self.resolved_images = request.images
                return GradeResponse(normalized_score=1.0)

        provider = TrackingProvider()
        judge = SyncJudge(client=None, instance_id="test", llm_provider=provider)
        judge.grade(
            "test rubric",
            "submission",
            images={"gold": Image.from_path("gold.png")},
        )

        assert provider.resolved_images is not None
        assert provider.resolved_images["gold"].source == "base64"
        assert provider.resolved_images["gold"].data == "RESOLVED"


# ---------------------------------------------------------------------------
# ExternalProvider with from_path images in request body
# ---------------------------------------------------------------------------


class TestExternalProviderPathImages:
    def test_path_image_resolved_in_request_body(self):
        """from_path images are resolved to base64 in the LLM request body."""
        raw_bytes = b"\x89PNG\r\n\x1a\nfake-png"
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(raw_bytes)
            path = f.name
        try:
            provider = ExternalProvider(api_key="sk-test", model="test/model")
            img = Image.from_path(path)
            req = GradeRequest(
                rubric="Test rubric",
                submission="Answer",
                images={"screenshot": img},
            )
            body = provider._build_request_body(req)

            user_msg = body["messages"][1]
            content_blocks = user_msg["content"]
            image_blocks = [b for b in content_blocks if b.get("type") == "image_url"]
            assert len(image_blocks) == 1
            assert image_blocks[0]["image_url"]["url"].startswith("data:image/png;base64,")
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# ExternalProvider file handling in request body
# ---------------------------------------------------------------------------


class TestExternalProviderFiles:
    def test_text_file_included_in_request_body(self):
        """Text files are inlined as text blocks in the LLM request."""
        with tempfile.NamedTemporaryFile(suffix=".csv", mode="w", delete=False) as f:
            f.write("name,score\nAlice,95\nBob,87\n")
            path = f.name
        try:
            provider = ExternalProvider(api_key="sk-test", model="test/model")
            req = GradeRequest(
                rubric="Test rubric",
                submission="Answer",
                files={"data": File.from_local(path, media_type="text/csv")},
            )
            body = provider._build_request_body(req)

            user_msg = body["messages"][1]
            content_blocks = user_msg["content"]
            text_blocks = [b for b in content_blocks if b.get("type") == "text"]
            # Should have a file block + the main user message
            file_blocks = [b for b in text_blocks if "## File:" in b.get("text", "")]
            assert len(file_blocks) == 1
            assert "Alice,95" in file_blocks[0]["text"]
        finally:
            os.unlink(path)

    def test_base64_file_included_in_request_body(self):
        """Base64-encoded files are decoded and inlined as text."""
        content = "Hello, world!"
        b64_data = base64.b64encode(content.encode()).decode()
        provider = ExternalProvider(api_key="sk-test", model="test/model")
        req = GradeRequest(
            rubric="Test rubric",
            submission="Answer",
            files={"readme": File.from_base64(b64_data, "readme.txt", media_type="text/plain")},
        )
        body = provider._build_request_body(req)

        user_msg = body["messages"][1]
        text_blocks = [b for b in user_msg["content"] if b.get("type") == "text"]
        file_blocks = [b for b in text_blocks if "## File:" in b.get("text", "")]
        assert len(file_blocks) == 1
        assert "Hello, world!" in file_blocks[0]["text"]

    def test_path_file_included_in_request_body(self):
        """from_path files are read from disk and inlined."""
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            json.dump({"key": "value"}, f)
            path = f.name
        try:
            provider = ExternalProvider(api_key="sk-test", model="test/model")
            req = GradeRequest(
                rubric="Test rubric",
                submission="Answer",
                files={"config": File.from_path(path)},
            )
            body = provider._build_request_body(req)

            user_msg = body["messages"][1]
            text_blocks = [b for b in user_msg["content"] if b.get("type") == "text"]
            file_blocks = [b for b in text_blocks if "## File:" in b.get("text", "")]
            assert len(file_blocks) == 1
            assert '"key"' in file_blocks[0]["text"]
        finally:
            os.unlink(path)

    def test_unresolvable_file_skipped(self):
        """Files that can't be resolved are skipped with a warning."""
        provider = ExternalProvider(api_key="sk-test", model="test/model")
        req = GradeRequest(
            rubric="Test rubric",
            submission="Answer",
            files={"missing": File.from_local("/nonexistent/file.csv")},
        )
        body = provider._build_request_body(req)

        user_msg = body["messages"][1]
        text_blocks = [b for b in user_msg["content"] if b.get("type") == "text"]
        file_blocks = [b for b in text_blocks if "## File:" in b.get("text", "")]
        assert len(file_blocks) == 0


# ---------------------------------------------------------------------------
# ExternalProvider error handling
# ---------------------------------------------------------------------------


class TestExternalProviderErrorHandling:
    def test_http_error_returns_zero_grade(self):
        """HTTP errors return GradeResponse with 0.0 score instead of raising."""
        provider = ExternalProvider(api_key="sk-test", model="test/model")

        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Server Error", request=MagicMock(), response=mock_response,
        )

        with patch("httpx.Client") as MockClient:
            mock_client = MagicMock()
            mock_client.post.return_value = mock_response
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_client

            req = _make_grade_request()
            resp = provider.grade(req)

            assert resp.normalized_score == 0.0
            assert "LLM API error" in resp.feedback
            assert "500" in resp.feedback

    def test_request_error_returns_zero_grade(self):
        """Network errors return GradeResponse with 0.0 score instead of raising."""
        provider = ExternalProvider(api_key="sk-test", model="test/model")

        with patch("httpx.Client") as MockClient:
            mock_client = MagicMock()
            mock_client.post.side_effect = httpx.RequestError("Connection refused")
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            MockClient.return_value = mock_client

            req = _make_grade_request()
            resp = provider.grade(req)

            assert resp.normalized_score == 0.0
            assert "request failed" in resp.feedback.lower()


# ---------------------------------------------------------------------------
# ExternalProvider api_key validation
# ---------------------------------------------------------------------------


class TestExternalProviderValidation:
    def test_empty_api_key_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            ExternalProvider(api_key="")

    def test_whitespace_api_key_raises(self):
        with pytest.raises(ValueError, match="non-empty"):
            ExternalProvider(api_key="   ")


# ---------------------------------------------------------------------------
# Async: ExternalProvider.agrade()
# ---------------------------------------------------------------------------


class TestExternalProviderAsync:
    @pytest.mark.asyncio
    async def test_agrade_with_mocked_httpx(self):
        """ExternalProvider.agrade() uses httpx.AsyncClient correctly."""
        provider = ExternalProvider(
            api_key="sk-test",
            base_url="https://test-api.example.com/v1",
            model="test/model",
        )

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [{"message": {"content": _mock_llm_json_response()}}],
        }
        mock_response.raise_for_status = MagicMock()

        with patch("fleet.llm_provider.httpx.AsyncClient") as MockAsyncClient:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockAsyncClient.return_value = mock_client

            req = _make_grade_request()
            resp = await provider.agrade(req)

            mock_client.post.assert_called_once()
            assert resp.normalized_score == pytest.approx(13 / 15, abs=0.01)
            assert len(resp.criteria) == 2

    @pytest.mark.asyncio
    async def test_agrade_http_error_returns_zero(self):
        """Async HTTP errors return GradeResponse with 0.0 score."""
        provider = ExternalProvider(api_key="sk-test", model="test/model")

        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.text = "Rate limited"
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Rate limited", request=MagicMock(), response=mock_response,
        )

        with patch("fleet.llm_provider.httpx.AsyncClient") as MockAsyncClient:
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_response
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockAsyncClient.return_value = mock_client

            req = _make_grade_request()
            resp = await provider.agrade(req)

            assert resp.normalized_score == 0.0
            assert "429" in resp.feedback


# ---------------------------------------------------------------------------
# Async: LLMProvider.agrade() default (run_in_executor)
# ---------------------------------------------------------------------------


class TestLLMProviderAgradeDefault:
    @pytest.mark.asyncio
    async def test_default_agrade_calls_grade_without_blocking(self):
        """Base class agrade() offloads to executor so it doesn't block."""

        class SyncOnlyProvider(LLMProvider):
            def grade(self, request: GradeRequest) -> GradeResponse:
                return GradeResponse(
                    normalized_score=0.75,
                    model_used="sync-model",
                    provider_used="sync-provider",
                )

        provider = SyncOnlyProvider()
        req = _make_grade_request()
        resp = await provider.agrade(req)

        assert resp.normalized_score == 0.75
        assert resp.model_used == "sync-model"


# ---------------------------------------------------------------------------
# Async: AsyncJudge + provider integration
# ---------------------------------------------------------------------------


class TestAsyncJudgeWithProvider:
    @pytest.mark.asyncio
    async def test_async_judge_routes_through_provider(self):
        """AsyncJudge.grade() calls provider.agrade() when provider is set."""
        from fleet._async.judge import AsyncJudge

        mock_provider = AsyncMock(spec=LLMProvider)
        mock_provider.agrade.return_value = GradeResponse(
            normalized_score=0.9,
            total_score=9,
            max_score=10,
            criteria=[{"name": "Test", "score": 9, "max_score": 10, "reasoning": "Good"}],
            feedback="Nice work",
            model_used="test-model",
            provider_used="test-provider",
        )
        mock_provider.resolve_images.return_value = None
        mock_provider.resolve_files.return_value = None

        judge = AsyncJudge(client=None, instance_id="test", llm_provider=mock_provider)
        result = await judge.grade("Test rubric", "My submission")

        mock_provider.agrade.assert_called_once()
        assert float(result) == pytest.approx(0.9)
