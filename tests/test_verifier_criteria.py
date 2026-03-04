"""Tests for structured criteria scoring in verifier functions.

Tests that verifier __call__, _process_result, and remote methods correctly
handle dict return values with structured criteria.
"""

from fleet.verifiers.verifier import SyncVerifierFunction
from fleet.verifiers.decorator import SyncVerifierFunction as DecoratorSyncVerifierFunction


class TestSyncVerifierCriteriaScoring:
    """Tests for sync verifier (fleet/verifiers/verifier.py)."""

    def _make_verifier(self, func):
        return SyncVerifierFunction(
            func=func,
            key="test",
            extra_requirements=[],
            verifier_id="test-id",
        )

    def test_call_returns_float_for_plain_score(self):
        """Plain float return is preserved."""
        v = self._make_verifier(lambda env: 0.84)
        result = v(None)
        assert result == 0.84
        assert isinstance(result, float)

    def test_call_returns_dict_with_score_key(self):
        """Dict with 'score' key is returned as-is."""
        data = {"score": 0.84, "criteria": [{"criteria": "A", "score": 0.84, "score_out_of": 1.0}]}
        v = self._make_verifier(lambda env: data)
        result = v(None)
        assert isinstance(result, dict)
        assert result["score"] == 0.84
        assert len(result["criteria"]) == 1

    def test_call_returns_dict_with_result_key(self):
        """Dict with 'result' key (PR #1737 convention) is returned as-is."""
        data = {
            "result": 0.84,
            "criteria": [
                {"criteria": "Accuracy", "score": 0.95, "score_out_of": 1.0},
                {"criteria": "Quality", "score": 0.6, "score_out_of": 1.0},
            ],
        }
        v = self._make_verifier(lambda env: data)
        result = v(None)
        assert isinstance(result, dict)
        assert result["result"] == 0.84
        assert len(result["criteria"]) == 2

    def test_process_result_float(self):
        """_process_result returns float for plain score."""
        v = self._make_verifier(lambda env: 1.0)
        assert v._process_result(0.84) == 0.84

    def test_process_result_dict_with_criteria_preserved(self):
        """_process_result preserves dict when criteria are present."""
        data = {
            "result": 0.84,
            "criteria": [{"criteria": "A", "score": 0.84, "score_out_of": 1.0}],
        }
        v = self._make_verifier(lambda env: 1.0)
        result = v._process_result(data)
        assert isinstance(result, dict)
        assert result["result"] == 0.84
        assert "criteria" in result

    def test_process_result_dict_without_criteria_extracts_score(self):
        """_process_result extracts numeric score when no criteria."""
        v = self._make_verifier(lambda env: 1.0)
        result = v._process_result({"score": 0.5})
        assert result == 0.5
        assert isinstance(result, float)

    def test_process_result_dict_with_result_key_no_criteria(self):
        """_process_result extracts numeric score from 'result' key when no criteria."""
        v = self._make_verifier(lambda env: 1.0)
        result = v._process_result({"result": 0.7})
        assert result == 0.7
        assert isinstance(result, float)

    def test_call_error_returns_zero(self):
        """Errors in verifier function return 0.0."""
        v = self._make_verifier(lambda env: (_ for _ in ()).throw(ValueError("boom")))
        # A function that raises
        def bad_func(env):
            raise ValueError("boom")
        v2 = self._make_verifier(bad_func)
        result = v2(None)
        assert result == 0.0


class TestDecoratorSyncVerifierCriteriaScoring:
    """Tests for decorator verifier (fleet/verifiers/decorator.py)."""

    def _make_verifier(self, func):
        return DecoratorSyncVerifierFunction(
            func=func,
            key="test",
            verifier_id="test-id",
        )

    def test_call_returns_dict_with_result_key(self):
        """Dict with 'result' key is returned as-is (decorator version)."""
        data = {
            "result": 0.84,
            "criteria": [{"criteria": "A", "score": 0.84, "score_out_of": 1.0}],
        }
        v = self._make_verifier(lambda env: data)
        result = v(None)
        assert isinstance(result, dict)
        assert result["result"] == 0.84

    def test_call_returns_float_for_plain_score(self):
        """Plain float return is preserved (decorator version)."""
        v = self._make_verifier(lambda env: 0.5)
        result = v(None)
        assert result == 0.5
        assert isinstance(result, float)
