"""Unit tests for fleet.judge module.

Tests the portable judge infrastructure (no LLM calls, no MCP):
- Judge ABC contract
- Model resolution
- JSON extraction
- Response building / normalization
- Base64 image resolution
- McpClient basics
- Subclassing pattern
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pytest

from fleet.judge import (
    Judge,
    JudgeGradeRequest,
    JudgeGradeResponse,
    McpClient,
    StringRubric,
    StructuredRubric,
    Criterion,
    Base64ImageSource,
    S3ImageSource,
    build_grade_response,
    extract_json_from_response,
    resolve_base64_images,
    resolve_model,
)


# ---------------------------------------------------------------------------
# Concrete Judge subclass for testing
# ---------------------------------------------------------------------------


class StubJudge(Judge):
    """Minimal Judge subclass for testing the ABC contract."""

    def build_prompt(
        self,
        request: JudgeGradeRequest,
        image_blocks: List[Dict[str, Any]],
        file_blocks: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[str, List[Dict[str, Any]]]:
        system = "You are a test judge."
        user = [{"type": "text", "text": f"Evaluate: {request.submission}"}]
        if image_blocks:
            user.extend(image_blocks)
        return system, user


# ---------------------------------------------------------------------------
# Judge ABC
# ---------------------------------------------------------------------------


class TestJudgeABC:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            Judge(api_key="test")  # type: ignore[abstract]

    def test_subclass_instantiation(self):
        judge = StubJudge(api_key="test-key")
        assert judge.api_key == "test-key"
        assert judge.model == "claude-opus-4-6"
        assert judge.max_turns == 10

    def test_custom_model(self):
        judge = StubJudge(api_key="test-key", model="claude-sonnet-4-6")
        assert judge.model == "claude-sonnet-4-6"

    def test_progress_callback(self):
        calls = []
        judge = StubJudge(api_key="test-key", on_progress=calls.append)
        judge.on_progress("test")
        assert calls == ["test"]

    def test_build_prompt_contract(self):
        judge = StubJudge(api_key="test-key")
        request = JudgeGradeRequest(
            submission="Hello",
            rubric=StringRubric(text="Grade it"),
        )
        system, user_blocks = judge.build_prompt(request, [])
        assert isinstance(system, str)
        assert isinstance(user_blocks, list)
        assert "test judge" in system
        assert any("Hello" in b.get("text", "") for b in user_blocks)

    def test_parse_response_default(self):
        judge = StubJudge(api_key="test-key")
        result = judge.parse_response('{"score": 8, "max_score": 10, "feedback": "Good"}')
        assert result["score"] == 8

    def test_parse_response_override(self):
        class CustomParserJudge(StubJudge):
            def parse_response(self, raw_text):
                return {"score": 42, "max_score": 42, "feedback": "custom"}

        judge = CustomParserJudge(api_key="test-key")
        result = judge.parse_response("anything")
        assert result["score"] == 42

    def test_build_response_default(self):
        judge = StubJudge(api_key="test-key")
        request = JudgeGradeRequest(
            submission="test",
            rubric=StringRubric(text="evaluate"),
        )
        response = judge.build_response(
            parsed={"score": 7, "max_score": 10, "feedback": "Good"},
            raw_text="...",
            model_used="claude-opus-4-6",
            request=request,
            errors=[],
            elapsed_ms=100.0,
        )
        assert isinstance(response, JudgeGradeResponse)
        assert response.normalized_score == 0.7


# ---------------------------------------------------------------------------
# Model resolution
# ---------------------------------------------------------------------------


class TestResolveModel:
    def test_known_short_name(self):
        assert resolve_model("claude-opus-4.6") == "claude-opus-4-6"
        assert resolve_model("claude-sonnet-4.5") == "claude-sonnet-4-5-20250929"

    def test_already_full_id(self):
        assert resolve_model("claude-opus-4-6") == "claude-opus-4-6"

    def test_unknown_passes_through(self):
        assert resolve_model("custom-model-v1") == "custom-model-v1"


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------


class TestExtractJson:
    def test_fenced_json_block(self):
        text = 'Reasoning...\n```json\n{"score": 8, "max_score": 10, "feedback": "Good"}\n```'
        result = extract_json_from_response(text)
        assert result["score"] == 8

    def test_bare_json(self):
        text = 'I think this is great.\n{"score": 5, "max_score": 10, "feedback": "OK"}'
        result = extract_json_from_response(text)
        assert result["score"] == 5

    def test_trailing_comma_repair(self):
        text = '{"score": 5, "max_score": 10, "feedback": "OK",}'
        result = extract_json_from_response(text)
        assert result["score"] == 5

    def test_no_json_raises(self):
        with pytest.raises(ValueError, match="Could not extract JSON"):
            extract_json_from_response("No JSON here at all")

    def test_nested_braces_in_reasoning(self):
        text = (
            'The code uses {brackets} properly. '
            '{"score": 7, "max_score": 10, "feedback": "Decent"}'
        )
        result = extract_json_from_response(text)
        assert result["score"] == 7


# ---------------------------------------------------------------------------
# Response building
# ---------------------------------------------------------------------------


class TestBuildGradeResponse:
    def test_string_rubric(self):
        request = JudgeGradeRequest(
            submission="test",
            rubric=StringRubric(text="evaluate"),
        )
        response = build_grade_response(
            parsed={"score": 7, "max_score": 10, "feedback": "Good work"},
            raw_text="...",
            model_used="claude-opus-4-6",
            request=request,
            errors=[],
            elapsed_ms=100.0,
        )
        assert response.normalized_score == 0.7
        assert response.total_score == 7
        assert response.max_score == 10

    def test_structured_rubric(self):
        request = JudgeGradeRequest(
            submission="test",
            rubric=StructuredRubric(
                criteria=[Criterion(name="A", description="...", max_score=10.0)]
            ),
        )
        response = build_grade_response(
            parsed={
                "criteria": [{"name": "A", "score": 8, "max_score": 10, "reasoning": "Good"}],
                "total_score": 8,
                "max_score": 10,
                "feedback": "Well done",
            },
            raw_text="...",
            model_used="claude-opus-4-6",
            request=request,
            errors=[],
            elapsed_ms=200.0,
        )
        assert response.normalized_score == 0.8
        assert len(response.criteria) == 1

    def test_clamp_to_one(self):
        request = JudgeGradeRequest(
            submission="test",
            rubric=StringRubric(text="evaluate"),
        )
        response = build_grade_response(
            parsed={"score": 15, "max_score": 10, "feedback": ""},
            raw_text="...",
            model_used="claude-opus-4-6",
            request=request,
            errors=[],
            elapsed_ms=50.0,
        )
        assert response.normalized_score == 1.0

    def test_errors_in_accumulators(self):
        request = JudgeGradeRequest(
            submission="test",
            rubric=StringRubric(text="evaluate"),
        )
        response = build_grade_response(
            parsed={"score": 5, "max_score": 10, "feedback": "OK"},
            raw_text="...",
            model_used="claude-opus-4-6",
            request=request,
            errors=["S3 fetch failed"],
            elapsed_ms=100.0,
        )
        assert "errors" in response.accumulators


# ---------------------------------------------------------------------------
# Base64 image resolution
# ---------------------------------------------------------------------------


class TestResolveBase64Images:
    def test_base64_source(self):
        images = [Base64ImageSource(data="iVBOR...", media_type="image/png", label="screenshot")]
        blocks, errors = resolve_base64_images(images)
        assert len(blocks) == 2  # label + image
        assert blocks[1]["type"] == "image"
        assert not errors

    def test_s3_source_returns_error(self):
        images = [S3ImageSource(url="s3://bucket/key.png")]
        blocks, errors = resolve_base64_images(images)
        assert len(blocks) == 0
        assert len(errors) == 1


# ---------------------------------------------------------------------------
# McpClient basics
# ---------------------------------------------------------------------------


class TestMcpClient:
    def test_init(self):
        client = McpClient("https://example.com/mcp")
        assert client.url == "https://example.com/mcp"
        assert client.session_id is None

    def test_headers_without_session(self):
        client = McpClient("https://example.com/mcp")
        headers = client._headers()
        assert "Accept" in headers
        assert "Mcp-Session-Id" not in headers

    def test_headers_with_session(self):
        client = McpClient("https://example.com/mcp")
        client.session_id = "test-session-123"
        assert client._headers()["Mcp-Session-Id"] == "test-session-123"

    def test_request_ids_increment(self):
        client = McpClient("https://example.com/mcp")
        id1 = client._next_req_id()
        id2 = client._next_req_id()
        assert id2 == id1 + 1
