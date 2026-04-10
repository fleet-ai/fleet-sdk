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

"""Async LLM-as-a-judge grading module for Fleet SDK."""

import json
from typing import Dict, List, Optional

import httpx

from ..judge import (
    Criterion,
    JudgeEndpointConfig,
    JudgeResult,
    Rubric,
    _SYSTEM_PROMPT,
)


class AsyncJudgeService:
    """Asynchronous LLM-as-a-judge grading service."""

    def __init__(self, config: JudgeEndpointConfig) -> None:
        self.config = config
        self._client = httpx.AsyncClient(timeout=120.0)

    async def grade(
        self,
        rubric: Rubric,
        submission: str,
        files: Optional[Dict[str, str]] = None,
        conversation: Optional[List[Dict]] = None,
    ) -> JudgeResult:
        """Grade a submission against a rubric using the configured LLM endpoint."""
        messages = self._build_prompt(rubric, submission, files, conversation)
        if self.config.api_format == "anthropic":
            raw = await self._call_anthropic(messages)
        else:
            raw = await self._call_openai(messages)
        return self._parse_response(raw, rubric)

    def _build_prompt(
        self,
        rubric: Rubric,
        submission: str,
        files: Optional[Dict[str, str]] = None,
        conversation: Optional[List[Dict]] = None,
    ) -> List[Dict]:
        """Construct the messages array for the LLM call."""
        parts: List[str] = []

        if rubric.task_context:
            parts.append(f"## Task Context\n{rubric.task_context}")

        parts.append("## Evaluation Criteria")
        for criterion in rubric.criteria:
            parts.append(f"\n### {criterion.name} (max score: {criterion.max_score})")
            for score, description in sorted(criterion.levels.items()):
                parts.append(f"  - Score {score}: {description}")

        parts.append(f"\n## Submission\n{submission}")

        if files:
            parts.append("\n## Files")
            for filename, content in files.items():
                parts.append(f"\n### {filename}\n```\n{content}\n```")

        if conversation:
            parts.append("\n## Conversation History")
            for msg in conversation:
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                parts.append(f"\n**{role}**: {content}")

        return [{"role": "user", "content": "\n".join(parts)}]

    async def _call_anthropic(self, messages: List[Dict]) -> str:
        """Call an Anthropic-format endpoint."""
        url = self.config.url
        if not url.rstrip("/").endswith("/v1/messages"):
            url = url.rstrip("/") + "/v1/messages"

        response = await self._client.post(
            url,
            headers={
                "x-api-key": self.config.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": self.config.model,
                "max_tokens": 4096,
                "system": _SYSTEM_PROMPT,
                "messages": messages,
            },
        )
        response.raise_for_status()
        data = response.json()
        for block in data.get("content", []):
            if block.get("type") == "text":
                return block["text"]
        return ""

    async def _call_openai(self, messages: List[Dict]) -> str:
        """Call an OpenAI-format endpoint."""
        url = self.config.url
        if not url.rstrip("/").endswith("/v1/chat/completions"):
            url = url.rstrip("/") + "/v1/chat/completions"

        all_messages = [{"role": "system", "content": _SYSTEM_PROMPT}] + messages
        response = await self._client.post(
            url,
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.config.model,
                "messages": all_messages,
                "response_format": {"type": "json_object"},
            },
        )
        response.raise_for_status()
        data = response.json()
        choices = data.get("choices", [])
        if choices:
            return choices[0].get("message", {}).get("content", "")
        return ""

    def _parse_response(self, raw_response: str, rubric: Rubric) -> JudgeResult:
        """Parse the LLM JSON response into a JudgeResult."""
        scores: Dict[str, float] = {}
        reasoning: Dict[str, str] = {}
        max_total = sum(c.max_score for c in rubric.criteria)

        try:
            data = json.loads(raw_response)
            raw_scores = data.get("scores", {})
            for criterion in rubric.criteria:
                entry = raw_scores.get(criterion.name, {})
                if isinstance(entry, dict):
                    scores[criterion.name] = float(entry.get("score", 0))
                    reasoning[criterion.name] = str(entry.get("reasoning", ""))
                else:
                    scores[criterion.name] = 0.0
                    reasoning[criterion.name] = ""
        except (json.JSONDecodeError, ValueError, TypeError):
            for criterion in rubric.criteria:
                scores[criterion.name] = 0.0
                reasoning[criterion.name] = ""

        total = sum(scores.values())
        normalized = total / max_total if max_total > 0 else 0.0

        return JudgeResult(
            scores=scores,
            total=total,
            max_total=float(max_total),
            normalized=normalized,
            reasoning=reasoning,
        )
