"""Tests for structured criteria stdout markers in fleet.judge.

Validates that _print_criteria_markers emits the correct
>>> CRITERIA >>> / <<< CRITERIA <<< markers that the orchestrator
(theseus PR #1967) and client (client PR #1737) expect.
"""

import json
import re
from io import StringIO
from unittest.mock import patch

import pytest

from fleet.judge import (
    _print_criteria_markers,
    _print_judge_result,
    _parse_grade_response,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MARKER_RE = re.compile(
    r">>> CRITERIA >>>\s*\n(.*?)\n<<< CRITERIA <<<",
    re.DOTALL,
)


def _capture_print(fn, *args, **kwargs):
    """Capture all print() output from a function call."""
    buf = StringIO()
    with patch("builtins.print", side_effect=lambda *a, **kw: buf.write(" ".join(str(x) for x in a) + "\n")):
        fn(*args, **kwargs)
    return buf.getvalue()


def _extract_criteria_from_stdout(stdout: str):
    """Mirror the orchestrator's extraction logic (theseus PR #1967)."""
    m = _MARKER_RE.search(stdout)
    if not m:
        return None
    parsed = json.loads(m.group(1).strip())
    if isinstance(parsed, list):
        return parsed
    return None


# ---------------------------------------------------------------------------
# _print_criteria_markers
# ---------------------------------------------------------------------------

class TestPrintCriteriaMarkers:
    """Tests for _print_criteria_markers."""

    def test_basic_criteria_output(self):
        """Emits valid markers with normalised scores."""
        criteria = [
            {"name": "Accuracy", "score": 8, "max_score": 10, "reasoning": "Good job"},
            {"name": "Style", "score": 5, "max_score": 5, "reasoning": "Perfect"},
        ]
        stdout = _capture_print(_print_criteria_markers, criteria)

        parsed = _extract_criteria_from_stdout(stdout)
        assert parsed is not None, f"Markers not found in stdout:\n{stdout}"
        assert len(parsed) == 2

        assert parsed[0]["criteria"] == "Accuracy"
        assert parsed[0]["score"] == pytest.approx(0.8, abs=0.01)
        assert parsed[0]["score_out_of"] == 1.0
        assert parsed[0]["description"] == "Good job"

        assert parsed[1]["criteria"] == "Style"
        assert parsed[1]["score"] == pytest.approx(1.0, abs=0.01)
        assert parsed[1]["score_out_of"] == 1.0

    def test_zero_max_score_passthrough(self):
        """When max_score is 0, raw score passes through."""
        criteria = [
            {"name": "Metric", "score": 0.75, "max_score": 0},
        ]
        stdout = _capture_print(_print_criteria_markers, criteria)
        parsed = _extract_criteria_from_stdout(stdout)
        assert parsed is not None
        assert parsed[0]["score"] == pytest.approx(0.75, abs=0.01)

    def test_empty_criteria_no_markers(self):
        """Empty list should produce no markers."""
        stdout = _capture_print(_print_criteria_markers, [])
        assert ">>> CRITERIA >>>" not in stdout

    def test_reasoning_maps_to_description(self):
        """The 'reasoning' field maps to 'description' in the marker schema."""
        criteria = [
            {"name": "Test", "score": 3, "max_score": 5, "reasoning": "Some reasoning here"},
        ]
        stdout = _capture_print(_print_criteria_markers, criteria)
        parsed = _extract_criteria_from_stdout(stdout)
        assert parsed[0]["description"] == "Some reasoning here"

    def test_missing_reasoning_no_description(self):
        """When reasoning is empty, description key should be absent."""
        criteria = [
            {"name": "Test", "score": 3, "max_score": 5, "reasoning": ""},
        ]
        stdout = _capture_print(_print_criteria_markers, criteria)
        parsed = _extract_criteria_from_stdout(stdout)
        assert "description" not in parsed[0]

    def test_output_parseable_by_orchestrator_regex(self):
        """Ensure the output matches the exact regex the orchestrator uses."""
        criteria = [
            {"name": "A", "score": 1, "max_score": 2, "reasoning": "half"},
        ]
        stdout = _capture_print(_print_criteria_markers, criteria)

        # Use the exact regex from theseus PR #1967
        m = re.search(
            r">>> CRITERIA >>>\s*\n(.*?)\n<<< CRITERIA <<<",
            stdout,
            re.DOTALL,
        )
        assert m is not None, "Output doesn't match orchestrator regex"
        data = json.loads(m.group(1).strip())
        assert isinstance(data, list)
        assert data[0]["criteria"] == "A"


# ---------------------------------------------------------------------------
# _print_judge_result integration
# ---------------------------------------------------------------------------

class TestPrintJudgeResult:
    """Tests for _print_judge_result emitting criteria markers."""

    def test_criteria_markers_emitted(self):
        """_print_judge_result emits criteria markers when criteria present."""
        data = {
            "model_used": "claude-sonnet",
            "provider_used": "anthropic",
            "total_score": 15,
            "max_score": 20,
            "normalized_score": 0.75,
            "criteria": [
                {"name": "Accuracy", "score": 8, "max_score": 10, "reasoning": "Good"},
                {"name": "Style", "score": 7, "max_score": 10, "reasoning": "Decent"},
            ],
        }
        stdout = _capture_print(_print_judge_result, data)
        parsed = _extract_criteria_from_stdout(stdout)
        assert parsed is not None
        assert len(parsed) == 2

    def test_no_criteria_no_markers(self):
        """_print_judge_result doesn't emit markers when no criteria."""
        data = {
            "model_used": "claude-sonnet",
            "provider_used": "anthropic",
            "total_score": 0,
            "max_score": 0,
            "normalized_score": 0.5,
        }
        stdout = _capture_print(_print_judge_result, data)
        assert ">>> CRITERIA >>>" not in stdout


# ---------------------------------------------------------------------------
# _parse_grade_response integration
# ---------------------------------------------------------------------------

class TestParseGradeResponse:
    """Tests for _parse_grade_response emitting criteria markers."""

    def test_full_flow_emits_markers(self):
        """_parse_grade_response → _print_judge_result → criteria markers."""
        data = {
            "model_used": "claude-sonnet",
            "provider_used": "anthropic",
            "total_score": 9,
            "max_score": 10,
            "normalized_score": 0.9,
            "criteria": [
                {"name": "Completeness", "score": 9, "max_score": 10, "reasoning": "Almost perfect"},
            ],
        }
        stdout = _capture_print(_parse_grade_response, data)
        parsed = _extract_criteria_from_stdout(stdout)
        assert parsed is not None
        assert parsed[0]["criteria"] == "Completeness"
        assert parsed[0]["score"] == pytest.approx(0.9, abs=0.01)
