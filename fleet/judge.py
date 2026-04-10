"""Fleet SDK Judge — LLM-as-a-judge grading for Fleet environments."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Literal, Optional

import httpx
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Module-level global config (set via fleet.configure or directly)
# ---------------------------------------------------------------------------

_global_judge_config: Optional["JudgeEndpointConfig"] = None


def _get_judge_config() -> Optional["JudgeEndpointConfig"]:
    """Return the global judge endpoint config, if any."""
    return _global_judge_config


def _set_judge_config(config: Optional["JudgeEndpointConfig"]) -> None:
    global _global_judge_config
    _global_judge_config = config


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class JudgeEndpointConfig(BaseModel):
    """Configuration for a customer-provided LLM endpoint."""

    url: str = Field(..., description="The LLM endpoint URL")
    api_key: str = Field(..., description="Auth token for the endpoint")
    model: str = Field(
        "claude-sonnet-4-20250514", description="Model to use"
    )
    api_format: Literal["anthropic", "openai"] = Field(
        "anthropic", description="API format"
    )


class Criterion(BaseModel):
    """A single grading criterion."""

    name: str = Field(..., description="Criterion name")
    max_score: int = Field(..., alias="max", description="Maximum score for this criterion")
    levels: Dict[int, str] = Field(
        ..., description="Score level descriptions, e.g. {0: 'Poor', 1: 'Good'}"
    )

    model_config = {"populate_by_name": True}

    def __init__(self, name: str, *, max: int, levels: Dict[int, str], **kwargs: Any):
        super().__init__(name=name, max=max, levels=levels, **kwargs)


class Rubric(BaseModel):
    """A grading rubric composed of criteria."""

    criteria: List[Criterion]
    context: Optional[str] = Field(None, description="Task context/summary for the judge")
    instructions: Optional[str] = Field(None, description="Additional grading instructions")


class CriterionScore(BaseModel):
    """Score for a single criterion."""

    name: str
    score: int
    max_score: int
    reasoning: str


class JudgeResult(BaseModel):
    """Result of LLM-as-a-judge grading."""

    scores: List[CriterionScore]
    total_score: float = Field(..., description="Normalized score 0.0-1.0")
    raw_total: int
    max_total: int
    reasoning: str

    def __float__(self) -> float:
        return self.total_score


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

_JUDGE_SYSTEM_PROMPT = """\
You are an expert judge evaluating task submissions. You MUST respond with valid JSON only — no markdown, no extra text.

Evaluate the submission against each criterion in the rubric. For each criterion, assign a score and provide reasoning.

Respond with exactly this JSON structure:
{
  "scores": [
    {"name": "<criterion_name>", "score": <int>, "max_score": <int>, "reasoning": "<explanation>"}
  ],
  "reasoning": "<overall assessment>"
}"""


def _build_judge_prompt(
    rubric: Rubric,
    submission: Optional[str] = None,
    conversation: Optional[str] = None,
    files: Optional[Dict[str, Any]] = None,
    final_answer: Optional[str] = None,
) -> tuple:
    """Build system + user messages for the judge LLM.

    Returns (system_text, user_messages) where user_messages is a list of
    {"role": "user", "content": ...} dicts.
    """
    system = _JUDGE_SYSTEM_PROMPT

    # Build user message
    parts: List[str] = []

    if rubric.context:
        parts.append(f"## Task Context\n{rubric.context}")

    if rubric.instructions:
        parts.append(f"## Grading Instructions\n{rubric.instructions}")

    # Rubric description
    criteria_desc = []
    for c in rubric.criteria:
        levels_str = ", ".join(f"{k}: {v}" for k, v in sorted(c.levels.items()))
        criteria_desc.append(
            f"- **{c.name}** (max {c.max_score}): Levels — {levels_str}"
        )
    parts.append("## Rubric\n" + "\n".join(criteria_desc))

    if submission is not None:
        parts.append(f"## Submission\n{submission}")

    if conversation is not None:
        parts.append(f"## Conversation\n{conversation}")

    if files:
        file_parts = []
        for fname, content in files.items():
            file_parts.append(f"### {fname}\n```\n{content}\n```")
        parts.append("## Files\n" + "\n".join(file_parts))

    if final_answer is not None:
        parts.append(f"## Final Answer\n{final_answer}")

    user_content = "\n\n".join(parts)
    user_messages = [{"role": "user", "content": user_content}]
    return system, user_messages


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def _parse_judge_response(response_text: str, rubric: Rubric) -> JudgeResult:
    """Parse JSON response from the judge LLM into a JudgeResult."""
    # Strip markdown code fences if present
    text = response_text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if m:
        text = m.group(1).strip()

    data = json.loads(text)

    criterion_map = {c.name: c for c in rubric.criteria}
    scores: List[CriterionScore] = []

    for s in data["scores"]:
        name = s["name"]
        max_score = criterion_map[name].max_score if name in criterion_map else s.get("max_score", 0)
        scores.append(
            CriterionScore(
                name=name,
                score=s["score"],
                max_score=max_score,
                reasoning=s.get("reasoning", ""),
            )
        )

    raw_total = sum(s.score for s in scores)
    max_total = sum(s.max_score for s in scores)
    total_score = raw_total / max_total if max_total > 0 else 0.0

    return JudgeResult(
        scores=scores,
        total_score=total_score,
        raw_total=raw_total,
        max_total=max_total,
        reasoning=data.get("reasoning", ""),
    )


# ---------------------------------------------------------------------------
# LLM endpoint callers
# ---------------------------------------------------------------------------


def _call_anthropic_endpoint(
    config: JudgeEndpointConfig,
    system: str,
    messages: List[Dict[str, str]],
) -> str:
    """Call an Anthropic Messages API endpoint synchronously."""
    url = f"{config.url.rstrip('/')}/v1/messages"
    headers = {
        "x-api-key": config.api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": config.model,
        "max_tokens": 4096,
        "system": system,
        "messages": messages,
    }
    resp = httpx.post(url, json=payload, headers=headers, timeout=120.0)
    resp.raise_for_status()
    data = resp.json()
    # Extract text from content blocks
    return "".join(
        block.get("text", "") for block in data.get("content", [])
    )


def _call_openai_endpoint(
    config: JudgeEndpointConfig,
    system: str,
    messages: List[Dict[str, str]],
) -> str:
    """Call an OpenAI Chat Completions API endpoint synchronously."""
    url = f"{config.url.rstrip('/')}/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "content-type": "application/json",
    }
    all_messages = [{"role": "system", "content": system}] + messages
    payload = {
        "model": config.model,
        "messages": all_messages,
        "response_format": {"type": "json_object"},
    }
    resp = httpx.post(url, json=payload, headers=headers, timeout=120.0)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# Async LLM endpoint callers
# ---------------------------------------------------------------------------


async def _call_anthropic_endpoint_async(
    config: JudgeEndpointConfig,
    system: str,
    messages: List[Dict[str, str]],
) -> str:
    """Call an Anthropic Messages API endpoint asynchronously."""
    url = f"{config.url.rstrip('/')}/v1/messages"
    headers = {
        "x-api-key": config.api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": config.model,
        "max_tokens": 4096,
        "system": system,
        "messages": messages,
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, json=payload, headers=headers, timeout=120.0)
        resp.raise_for_status()
        data = resp.json()
        return "".join(
            block.get("text", "") for block in data.get("content", [])
        )


async def _call_openai_endpoint_async(
    config: JudgeEndpointConfig,
    system: str,
    messages: List[Dict[str, str]],
) -> str:
    """Call an OpenAI Chat Completions API endpoint asynchronously."""
    url = f"{config.url.rstrip('/')}/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "content-type": "application/json",
    }
    all_messages = [{"role": "system", "content": system}] + messages
    payload = {
        "model": config.model,
        "messages": all_messages,
        "response_format": {"type": "json_object"},
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, json=payload, headers=headers, timeout=120.0)
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# Judge (sync)
# ---------------------------------------------------------------------------


class Judge:
    """LLM-as-a-judge grading resource."""

    def __init__(
        self,
        orchestrator_client: Any = None,
        endpoint_config: Optional[JudgeEndpointConfig] = None,
        instance_id: Optional[str] = None,
    ):
        self._client = orchestrator_client
        self._config = endpoint_config
        self._instance_id = instance_id

    def grade(
        self,
        rubric: Rubric,
        submission: Optional[str] = None,
        conversation: Optional[str] = None,
        files: Optional[Dict[str, Any]] = None,
        final_answer: Optional[str] = None,
    ) -> JudgeResult:
        """Grade a submission using LLM-as-a-judge."""
        system, messages = _build_judge_prompt(
            rubric, submission=submission, conversation=conversation,
            files=files, final_answer=final_answer,
        )

        if self._config is not None:
            # Direct LLM call
            if self._config.api_format == "anthropic":
                response_text = _call_anthropic_endpoint(self._config, system, messages)
            else:
                response_text = _call_openai_endpoint(self._config, system, messages)
            return _parse_judge_response(response_text, rubric)

        # Orchestrator fallback
        if self._client is None:
            raise ValueError(
                "No judge endpoint configured and no orchestrator client available. "
                "Call fleet.configure(judge_endpoint=...) or provide an endpoint_config."
            )
        payload = {
            "rubric": rubric.model_dump(),
            "submission": submission,
            "conversation": conversation,
            "files": files,
            "final_answer": final_answer,
            "instance_id": self._instance_id,
        }
        resp = self._client.request("POST", "/v1/judge/grade", json=payload)
        return _parse_judge_response(
            resp.json().get("response", resp.text), rubric
        )


# ---------------------------------------------------------------------------
# AsyncJudge
# ---------------------------------------------------------------------------


class AsyncJudge:
    """Async LLM-as-a-judge grading resource."""

    def __init__(
        self,
        orchestrator_client: Any = None,
        endpoint_config: Optional[JudgeEndpointConfig] = None,
        instance_id: Optional[str] = None,
    ):
        self._client = orchestrator_client
        self._config = endpoint_config
        self._instance_id = instance_id

    async def grade(
        self,
        rubric: Rubric,
        submission: Optional[str] = None,
        conversation: Optional[str] = None,
        files: Optional[Dict[str, Any]] = None,
        final_answer: Optional[str] = None,
    ) -> JudgeResult:
        """Grade a submission using LLM-as-a-judge (async)."""
        system, messages = _build_judge_prompt(
            rubric, submission=submission, conversation=conversation,
            files=files, final_answer=final_answer,
        )

        if self._config is not None:
            if self._config.api_format == "anthropic":
                response_text = await _call_anthropic_endpoint_async(
                    self._config, system, messages,
                )
            else:
                response_text = await _call_openai_endpoint_async(
                    self._config, system, messages,
                )
            return _parse_judge_response(response_text, rubric)

        if self._client is None:
            raise ValueError(
                "No judge endpoint configured and no orchestrator client available. "
                "Call fleet.configure(judge_endpoint=...) or provide an endpoint_config."
            )
        payload = {
            "rubric": rubric.model_dump(),
            "submission": submission,
            "conversation": conversation,
            "files": files,
            "final_answer": final_answer,
            "instance_id": self._instance_id,
        }
        resp = await self._client.request("POST", "/v1/judge/grade", json=payload)
        return _parse_judge_response(
            resp.json().get("response", resp.text), rubric
        )
