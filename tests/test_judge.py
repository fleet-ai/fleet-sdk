# Copyright 2025 Fleet AI
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Tests for fleet.judge module."""

import json
import os
from unittest.mock import AsyncMock, patch

import pytest

from fleet.judge import (
    Criterion,
    CriterionResult,
    JudgeClient,
    JudgeEndpointConfig,
    JudgeResult,
    Rubric,
)
from fleet.judge.client import extract_json_from_response
from fleet.judge.prompt import build_structured_rubric_prompt


# ---------------------------------------------------------------------------
# Criterion & Rubric construction
# ---------------------------------------------------------------------------


class TestCriterion:
    def test_basic_construction(self):
        c = Criterion("Quality", max=10)
        assert c.name == "Quality"
        assert c.max_score == 10
        assert c.levels == {}
        assert c.description == ""

    def test_construction_with_levels(self):
        levels = {10: "Excellent", 7: "Good", 0: "Poor"}
        c = Criterion("Quality", max=10, levels=levels)
        assert c.levels == levels
        assert c.max_score == 10

    def test_construction_with_description(self):
        c = Criterion("Style", max=5, description="Code style")
        assert c.description == "Code style"

    def test_repr(self):
        c = Criterion("Quality", max=10)
        assert "Quality" in repr(c)
        assert "10" in repr(c)


class TestRubric:
    def test_construction(self):
        criteria = [
            Criterion("Quality", max=10),
            Criterion("Style", max=5),
        ]
        rubric = Rubric(criteria=criteria)
        assert len(rubric.criteria) == 2

    def test_max_score(self):
        rubric = Rubric(
            criteria=[
                Criterion("A", max=10),
                Criterion("B", max=5),
                Criterion("C", max=3),
            ]
        )
        assert rubric.max_score == 18

    def test_empty_rubric(self):
        rubric = Rubric(criteria=[])
        assert rubric.max_score == 0

    def test_repr(self):
        rubric = Rubric(criteria=[Criterion("A", max=10)])
        assert "1" in repr(rubric)
        assert "10" in repr(rubric)


# ---------------------------------------------------------------------------
# JudgeResult
# ---------------------------------------------------------------------------


class TestJudgeResult:
    def test_float_conversion(self):
        result = JudgeResult(
            normalized_score=0.85,
            total_score=8.5,
            max_score=10.0,
            criteria=[],
            feedback="Good work",
        )
        assert float(result) == 0.85

    def test_float_edge_cases(self):
        assert float(
            JudgeResult(
                normalized_score=0.0,
                total_score=0,
                max_score=10,
                criteria=[],
                feedback="",
            )
        ) == 0.0
        assert float(
            JudgeResult(
                normalized_score=1.0,
                total_score=10,
                max_score=10,
                criteria=[],
                feedback="",
            )
        ) == 1.0

    def test_criteria_iterable(self):
        cr = [
            CriterionResult("A", score=8, max_score=10, reasoning="ok"),
            CriterionResult("B", score=4, max_score=5, reasoning="good"),
        ]
        result = JudgeResult(
            normalized_score=0.8,
            total_score=12,
            max_score=15,
            criteria=cr,
            feedback="",
        )
        names = [c.name for c in result.criteria]
        assert names == ["A", "B"]

    def test_repr(self):
        result = JudgeResult(
            normalized_score=0.75,
            total_score=7.5,
            max_score=10,
            criteria=[
                CriterionResult("X", score=7.5, max_score=10, reasoning=""),
            ],
            feedback="",
        )
        r = repr(result)
        assert "0.7500" in r
        assert "1" in r

    def test_raw_response_optional(self):
        result = JudgeResult(
            normalized_score=0.5,
            total_score=5,
            max_score=10,
            criteria=[],
            feedback="",
        )
        assert result.raw_response is None

        result2 = JudgeResult(
            normalized_score=0.5,
            total_score=5,
            max_score=10,
            criteria=[],
            feedback="",
            raw_response='{"criteria": []}',
        )
        assert result2.raw_response is not None


# ---------------------------------------------------------------------------
# JSON extraction
# ---------------------------------------------------------------------------


class TestExtractJson:
    def test_bare_json(self):
        text = '{"criteria": [], "feedback": "ok"}'
        result = extract_json_from_response(text)
        assert result["feedback"] == "ok"

    def test_fenced_json(self):
        text = '```json\n{"criteria": [], "feedback": "ok"}\n```'
        result = extract_json_from_response(text)
        assert result["feedback"] == "ok"

    def test_fenced_no_language(self):
        text = '```\n{"criteria": [], "feedback": "ok"}\n```'
        result = extract_json_from_response(text)
        assert result["feedback"] == "ok"

    def test_trailing_comma_repair(self):
        text = '{"criteria": [{"name": "A", "score": 5,},], "feedback": "ok",}'
        result = extract_json_from_response(text)
        assert result["feedback"] == "ok"

    def test_surrounding_text(self):
        text = (
            "Here is my evaluation:\n\n"
            '```json\n{"criteria": [], "feedback": "done"}\n```\n\n'
            "I hope this helps!"
        )
        result = extract_json_from_response(text)
        assert result["feedback"] == "done"

    def test_no_json_raises(self):
        with pytest.raises(ValueError, match="No JSON found"):
            extract_json_from_response("no json here at all")

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError, match="Failed to parse"):
            extract_json_from_response("{not valid json content!!!}")


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


class TestPromptConstruction:
    def _make_rubric(self):
        return Rubric(
            criteria=[
                Criterion(
                    "Quality",
                    max=10,
                    levels={10: "Excellent", 5: "Average", 0: "Poor"},
                ),
                Criterion("Completeness", max=5, description="Is it complete?"),
            ]
        )

    def test_returns_tuple(self):
        rubric = self._make_rubric()
        result = build_structured_rubric_prompt(
            rubric=rubric, submission="test"
        )
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_system_prompt_contains_criteria(self):
        rubric = self._make_rubric()
        system, _ = build_structured_rubric_prompt(
            rubric=rubric, submission="test"
        )
        assert "Quality" in system
        assert "Completeness" in system
        assert "Excellent" in system
        assert "max 10" in system

    def test_user_message_contains_submission(self):
        rubric = self._make_rubric()
        _, user = build_structured_rubric_prompt(
            rubric=rubric, submission="my answer"
        )
        assert "my answer" in user
        assert "## Submission" in user

    def test_optional_fields_included(self):
        rubric = self._make_rubric()
        _, user = build_structured_rubric_prompt(
            rubric=rubric,
            submission="answer",
            ground_truth="expected",
            problem="the problem",
            context="some context",
            conversation=[
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "hi"},
            ],
        )
        assert "expected" in user
        assert "the problem" in user
        assert "some context" in user
        assert "hello" in user

    def test_optional_fields_omitted(self):
        rubric = self._make_rubric()
        _, user = build_structured_rubric_prompt(
            rubric=rubric, submission="answer"
        )
        assert "## Ground Truth" not in user
        assert "## Problem" not in user
        assert "## Context" not in user
        assert "## Conversation" not in user

    def test_system_prompt_requests_json(self):
        rubric = self._make_rubric()
        system, _ = build_structured_rubric_prompt(
            rubric=rubric, submission="test"
        )
        assert "JSON" in system


# ---------------------------------------------------------------------------
# JudgeEndpointConfig from env vars
# ---------------------------------------------------------------------------


class TestJudgeEndpointConfig:
    def test_manual_construction(self):
        cfg = JudgeEndpointConfig(
            url="http://localhost:8080",
            api_key="sk-test",
            model="gpt-4o",
            api_format="openai",
        )
        assert cfg.url == "http://localhost:8080"
        assert cfg.api_key == "sk-test"
        assert cfg.model == "gpt-4o"
        assert cfg.api_format == "openai"

    def test_defaults(self):
        cfg = JudgeEndpointConfig(url="http://x", api_key="k")
        assert cfg.model is None
        assert cfg.api_format == "anthropic"

    def test_repr(self):
        cfg = JudgeEndpointConfig(url="http://x", api_key="secret")
        r = repr(cfg)
        assert "http://x" in r
        assert "secret" not in r


# ---------------------------------------------------------------------------
# JudgeClient initialization
# ---------------------------------------------------------------------------


class TestJudgeClientInit:
    def test_explicit_config(self):
        cfg = JudgeEndpointConfig(url="http://x", api_key="k")
        client = JudgeClient(config=cfg)
        assert client._config is cfg

    def test_from_judge_env_vars(self):
        env = {
            "JUDGE_ENDPOINT": "http://judge:8080",
            "JUDGE_API_KEY": "sk-judge",
            "JUDGE_MODEL": "custom-model",
            "JUDGE_API_FORMAT": "openai",
        }
        with patch.dict(os.environ, env, clear=False):
            client = JudgeClient()
        assert client._config is not None
        assert client._config.url == "http://judge:8080"
        assert client._config.api_key == "sk-judge"
        assert client._config.model == "custom-model"
        assert client._config.api_format == "openai"

    def test_from_anthropic_key(self):
        env = {"ANTHROPIC_API_KEY": "sk-ant-test"}
        with patch.dict(os.environ, env, clear=False):
            # Clear JUDGE_* vars to avoid interference
            for k in [
                "JUDGE_ENDPOINT",
                "JUDGE_API_KEY",
                "JUDGE_MODEL",
                "JUDGE_API_FORMAT",
            ]:
                os.environ.pop(k, None)
            client = JudgeClient()
        assert client._config is not None
        assert client._config.api_format == "anthropic"
        assert client._config.api_key == "sk-ant-test"

    def test_no_config_available(self):
        with patch.dict(os.environ, {}, clear=True):
            client = JudgeClient()
        assert client._config is None

    def test_grade_raises_without_config(self):
        with patch.dict(os.environ, {}, clear=True):
            client = JudgeClient()
        rubric = Rubric(criteria=[Criterion("A", max=10)])
        with pytest.raises(ValueError, match="No judge endpoint configured"):
            client.grade_sync(rubric=rubric, submission="test")


# ---------------------------------------------------------------------------
# JudgeClient._parse_response
# ---------------------------------------------------------------------------


class TestParseResponse:
    def test_parse_valid_response(self):
        rubric = Rubric(
            criteria=[
                Criterion("Quality", max=10),
                Criterion("Style", max=5),
            ]
        )
        raw = json.dumps(
            {
                "criteria": [
                    {
                        "name": "Quality",
                        "score": 8,
                        "reasoning": "Good quality",
                    },
                    {
                        "name": "Style",
                        "score": 4,
                        "reasoning": "Nice style",
                    },
                ],
                "feedback": "Overall good work",
            }
        )
        result = JudgeClient._parse_response(raw, rubric)
        assert isinstance(result, JudgeResult)
        assert result.total_score == 12.0
        assert result.max_score == 15.0
        assert abs(result.normalized_score - 0.8) < 1e-9
        assert float(result) == result.normalized_score
        assert len(result.criteria) == 2
        assert result.criteria[0].name == "Quality"
        assert result.feedback == "Overall good work"
        assert result.raw_response == raw

    def test_parse_zero_max_score(self):
        rubric = Rubric(criteria=[])
        raw = json.dumps({"criteria": [], "feedback": "empty"})
        result = JudgeClient._parse_response(raw, rubric)
        assert result.normalized_score == 0.0
