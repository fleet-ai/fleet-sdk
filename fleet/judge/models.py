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

"""Data models for LLM-as-a-judge rubrics and results."""

from typing import Dict, List, Optional


class Criterion:
    """A single evaluation criterion for LLM-as-a-judge rubrics.

    Args:
        name: Name of the criterion.
        max: Maximum score for this criterion.
        levels: Dict mapping score -> description. Keys are score thresholds,
                values describe what that score means.
        description: Optional plain text description (alternative to levels).
    """

    def __init__(
        self,
        name: str,
        max: int,
        levels: Optional[Dict[int, str]] = None,
        description: Optional[str] = None,
    ):
        self.name = name
        self.max_score = max
        self.levels = levels or {}
        self.description = description or ""

    def __repr__(self) -> str:
        return f"Criterion(name={self.name!r}, max_score={self.max_score})"


class Rubric:
    """A structured rubric for LLM-as-a-judge evaluation.

    Args:
        criteria: List of Criterion objects.
    """

    def __init__(self, criteria: List[Criterion]):
        self.criteria = criteria

    @property
    def max_score(self) -> float:
        return sum(c.max_score for c in self.criteria)

    def __repr__(self) -> str:
        return f"Rubric(criteria={len(self.criteria)}, max_score={self.max_score})"


class CriterionResult:
    """Result for a single criterion."""

    def __init__(
        self,
        name: str,
        score: float,
        max_score: float,
        reasoning: str,
    ):
        self.name = name
        self.score = score
        self.max_score = max_score
        self.reasoning = reasoning

    def __repr__(self) -> str:
        return (
            f"CriterionResult(name={self.name!r}, "
            f"score={self.score}/{self.max_score})"
        )


class JudgeResult:
    """Result from judge grading. Supports float() conversion for normalized score."""

    def __init__(
        self,
        normalized_score: float,
        total_score: float,
        max_score: float,
        criteria: List[CriterionResult],
        feedback: str,
        raw_response: Optional[str] = None,
    ):
        self.normalized_score = normalized_score
        self.total_score = total_score
        self.max_score = max_score
        self.criteria = criteria
        self.feedback = feedback
        self.raw_response = raw_response

    def __float__(self) -> float:
        return self.normalized_score

    def __repr__(self) -> str:
        return (
            f"JudgeResult(score={self.normalized_score:.4f}, "
            f"criteria={len(self.criteria)})"
        )


class JudgeEndpointConfig:
    """Configuration for LLM endpoint used by judge.

    Args:
        url: Base URL of the LLM API endpoint.
        api_key: API key for authentication.
        model: Model name/ID to use. Defaults vary by provider.
        api_format: API format, either ``"anthropic"`` or ``"openai"``.
    """

    def __init__(
        self,
        url: str,
        api_key: str,
        model: Optional[str] = None,
        api_format: str = "anthropic",
    ):
        self.url = url
        self.api_key = api_key
        self.model = model
        self.api_format = api_format

    def __repr__(self) -> str:
        return (
            f"JudgeEndpointConfig(url={self.url!r}, "
            f"api_format={self.api_format!r})"
        )
