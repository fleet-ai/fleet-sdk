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

"""JudgeClient — LLM-as-a-judge grading client.

Supports two modes:
1. **Local mode** — calls an LLM endpoint directly (Anthropic or OpenAI format).
2. **Remote mode** — calls the Fleet orchestrator's ``/v1/judge/grade`` endpoint.

Configuration priority:
1. Explicit ``JudgeEndpointConfig`` passed to constructor.
2. Environment variables: ``JUDGE_ENDPOINT``, ``JUDGE_API_KEY``,
   ``JUDGE_MODEL``, ``JUDGE_API_FORMAT``.
3. ``ANTHROPIC_API_KEY`` env var (direct Anthropic API).
"""

import asyncio
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

import httpx

from fleet.judge.models import (
    CriterionResult,
    JudgeEndpointConfig,
    JudgeResult,
    Rubric,
)
from fleet.judge.prompt import build_structured_rubric_prompt

logger = logging.getLogger(__name__)

_DEFAULT_ANTHROPIC_URL = "https://api.anthropic.com"
_DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-20250514"
_DEFAULT_MAX_TOKENS = 4096
_REQUEST_TIMEOUT = 120.0


def extract_json_from_response(text: str) -> Dict[str, Any]:
    """Extract JSON from an LLM response that may contain markdown fencing.

    Handles:
    - Fenced code blocks (```json ... ``` or ``` ... ```)
    - Bare JSON objects
    - Trailing comma repair
    """
    # Try fenced code blocks first
    fenced = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if fenced:
        candidate = fenced.group(1).strip()
    else:
        # Try to find a bare JSON object
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            candidate = match.group(0).strip()
        else:
            raise ValueError(f"No JSON found in response: {text[:200]}")

    # Trailing comma repair: remove commas before closing brackets
    candidate = re.sub(r",\s*([}\]])", r"\1", candidate)

    try:
        return json.loads(candidate)  # type: ignore[no-any-return]
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Failed to parse JSON from response: {exc}\n{candidate[:500]}"
        ) from exc


class JudgeClient:
    """Client for LLM-as-a-judge grading.

    Can operate in two modes:

    1. **Remote mode** — Calls Fleet orchestrator's ``/v1/judge/grade`` endpoint.
    2. **Local mode** — Calls LLM endpoint directly (for offline/airgapped use).

    Configuration priority:

    1. Explicit ``JudgeEndpointConfig`` passed to constructor.
    2. Environment variables: ``JUDGE_ENDPOINT``, ``JUDGE_API_KEY``,
       ``JUDGE_MODEL``, ``JUDGE_API_FORMAT``.
    3. ``ANTHROPIC_API_KEY`` env var (direct Anthropic API).
    4. Fleet orchestrator (when used via ``env.judge``).
    """

    def __init__(
        self,
        config: Optional[JudgeEndpointConfig] = None,
        orchestrator_url: Optional[str] = None,
        orchestrator_token: Optional[str] = None,
    ):
        self._config = config or self._config_from_env()
        self._orchestrator_url = orchestrator_url
        self._orchestrator_token = orchestrator_token

    @staticmethod
    def _config_from_env() -> Optional[JudgeEndpointConfig]:
        """Attempt to build config from environment variables."""
        endpoint = os.environ.get("JUDGE_ENDPOINT")
        api_key = os.environ.get("JUDGE_API_KEY")
        if endpoint and api_key:
            return JudgeEndpointConfig(
                url=endpoint,
                api_key=api_key,
                model=os.environ.get("JUDGE_MODEL"),
                api_format=os.environ.get("JUDGE_API_FORMAT", "anthropic"),
            )

        anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
        if anthropic_key:
            return JudgeEndpointConfig(
                url=_DEFAULT_ANTHROPIC_URL,
                api_key=anthropic_key,
                model=_DEFAULT_ANTHROPIC_MODEL,
                api_format="anthropic",
            )

        return None

    async def grade(
        self,
        rubric: Rubric,
        submission: str,
        ground_truth: Optional[str] = None,
        problem: Optional[str] = None,
        context: Optional[str] = None,
        conversation: Optional[List[Dict[str, Any]]] = None,
        images: Optional[List[str]] = None,
        files: Optional[List[str]] = None,
        model: Optional[str] = None,
    ) -> JudgeResult:
        """Grade a submission using the configured LLM endpoint.

        Args:
            rubric: The rubric to evaluate against.
            submission: The submission text to grade.
            ground_truth: Optional expected answer or reference solution.
            problem: Optional problem statement.
            context: Optional additional context.
            conversation: Optional conversation history as list of
                ``{"role": ..., "content": ...}`` dicts.
            images: Optional list of image URLs or base64 data (reserved).
            files: Optional list of file paths (reserved).
            model: Optional model override for this call.

        Returns:
            A :class:`JudgeResult` with scores and feedback.

        Raises:
            ValueError: If no endpoint is configured.
            httpx.HTTPStatusError: If the LLM API returns an error.
        """
        if self._config is None:
            raise ValueError(
                "No judge endpoint configured. Set JUDGE_ENDPOINT and "
                "JUDGE_API_KEY environment variables, or pass a "
                "JudgeEndpointConfig to JudgeClient."
            )

        system_prompt, user_message = build_structured_rubric_prompt(
            rubric=rubric,
            submission=submission,
            ground_truth=ground_truth,
            problem=problem,
            context=context,
            conversation=conversation,
        )

        use_model = model or self._config.model

        if self._config.api_format == "openai":
            raw = await self._call_openai(
                system_prompt, user_message, use_model
            )
        else:
            raw = await self._call_anthropic(
                system_prompt, user_message, use_model
            )

        return self._parse_response(raw, rubric)

    def grade_sync(
        self,
        rubric: Rubric,
        submission: str,
        ground_truth: Optional[str] = None,
        problem: Optional[str] = None,
        context: Optional[str] = None,
        conversation: Optional[List[Dict[str, Any]]] = None,
        images: Optional[List[str]] = None,
        files: Optional[List[str]] = None,
        model: Optional[str] = None,
    ) -> JudgeResult:
        """Synchronous wrapper around :meth:`grade`."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(
                    asyncio.run,
                    self.grade(
                        rubric=rubric,
                        submission=submission,
                        ground_truth=ground_truth,
                        problem=problem,
                        context=context,
                        conversation=conversation,
                        images=images,
                        files=files,
                        model=model,
                    ),
                ).result()
        else:
            return asyncio.run(
                self.grade(
                    rubric=rubric,
                    submission=submission,
                    ground_truth=ground_truth,
                    problem=problem,
                    context=context,
                    conversation=conversation,
                    images=images,
                    files=files,
                    model=model,
                )
            )

    async def _call_anthropic(
        self,
        system_prompt: str,
        user_message: str,
        model: Optional[str],
    ) -> str:
        """Call the Anthropic Messages API."""
        url = self._config.url.rstrip("/")  # type: ignore[union-attr]
        api_key = self._config.api_key  # type: ignore[union-attr]
        model_id = model or _DEFAULT_ANTHROPIC_MODEL

        payload = {
            "model": model_id,
            "max_tokens": _DEFAULT_MAX_TOKENS,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_message}],
        }

        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            response = await client.post(
                f"{url}/v1/messages",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()

        data = response.json()
        # Extract text from the first content block
        content_blocks = data.get("content", [])
        parts = [
            block.get("text", "")
            for block in content_blocks
            if block.get("type") == "text"
        ]
        return "".join(parts)

    async def _call_openai(
        self,
        system_prompt: str,
        user_message: str,
        model: Optional[str],
    ) -> str:
        """Call an OpenAI-compatible Chat Completions API."""
        url = self._config.url.rstrip("/")  # type: ignore[union-attr]
        api_key = self._config.api_key  # type: ignore[union-attr]
        model_id = model or "gpt-4o"

        payload = {
            "model": model_id,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            "max_tokens": _DEFAULT_MAX_TOKENS,
            "temperature": 0,
        }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            response = await client.post(
                f"{url}/v1/chat/completions",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()

        data = response.json()
        choices = data.get("choices", [])
        if not choices:
            raise ValueError("OpenAI response contained no choices")
        return choices[0].get("message", {}).get("content", "")

    @staticmethod
    def _parse_response(raw: str, rubric: Rubric) -> JudgeResult:
        """Parse raw LLM response text into a JudgeResult."""
        parsed = extract_json_from_response(raw)

        criteria_results: List[CriterionResult] = []
        total_score = 0.0

        raw_criteria = parsed.get("criteria", [])
        # Build a lookup of rubric criteria by name for max_score
        rubric_lookup = {c.name: c for c in rubric.criteria}

        for item in raw_criteria:
            name = item.get("name", "")
            score = float(item.get("score", 0))
            reasoning = item.get("reasoning", "")
            rubric_criterion = rubric_lookup.get(name)
            max_score = (
                float(rubric_criterion.max_score)
                if rubric_criterion
                else score
            )
            criteria_results.append(
                CriterionResult(
                    name=name,
                    score=score,
                    max_score=max_score,
                    reasoning=reasoning,
                )
            )
            total_score += score

        max_score_total = rubric.max_score
        normalized = (
            total_score / max_score_total if max_score_total > 0 else 0.0
        )

        return JudgeResult(
            normalized_score=normalized,
            total_score=total_score,
            max_score=max_score_total,
            criteria=criteria_results,
            feedback=parsed.get("feedback", ""),
            raw_response=raw,
        )
