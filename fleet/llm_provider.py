"""LLM Provider abstraction for Fleet SDK Judge.

Defines a pluggable interface for routing LLM judge calls to either
the Fleet orchestrator (default) or external providers like OpenRouter,
Anthropic API, etc. This enables on-prem deployments that don't depend
on Fleet's internal orchestrator endpoints.

Configuration via environment variables (auto-detected at judge init)::

    # Set these env vars to route judge calls to an external provider.
    # When FLEET_LLM_API_KEY is unset, calls route through Fleet orchestrator.
    export FLEET_LLM_API_KEY="sk-or-..."                          # required
    export FLEET_LLM_BASE_URL="https://openrouter.ai/api/v1"     # optional (default: OpenRouter)
    export FLEET_LLM_MODEL="anthropic/claude-sonnet-4"            # optional (default: anthropic/claude-sonnet-4)
    export FLEET_LLM_TEMPERATURE="0.0"                            # optional (default: 0.0)
    export FLEET_LLM_MAX_TOKENS="4096"                            # optional (default: 4096)
    export FLEET_LLM_TIMEOUT="300"                                # optional (default: 300s)

Or configure programmatically::

    from fleet.llm_provider import ExternalProvider

    provider = ExternalProvider(
        api_key="sk-or-...",
        base_url="https://openrouter.ai/api/v1",
        model="anthropic/claude-sonnet-4",
    )
    judge = SyncJudge(client=None, instance_id="local", llm_provider=provider)
    result = judge.grade(rubric, submission)
"""

import json
import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union, TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from .judge import Rubric, Image, File

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Environment variable names
# ---------------------------------------------------------------------------

ENV_LLM_API_KEY = "FLEET_LLM_API_KEY"
ENV_LLM_BASE_URL = "FLEET_LLM_BASE_URL"
ENV_LLM_MODEL = "FLEET_LLM_MODEL"
ENV_LLM_TEMPERATURE = "FLEET_LLM_TEMPERATURE"
ENV_LLM_MAX_TOKENS = "FLEET_LLM_MAX_TOKENS"
ENV_LLM_TIMEOUT = "FLEET_LLM_TIMEOUT"


# ---------------------------------------------------------------------------
# Grade request / response types (provider-agnostic)
# ---------------------------------------------------------------------------


@dataclass
class GradeRequest:
    """Provider-agnostic grading request.

    Contains all the information needed to perform LLM-as-judge grading,
    independent of whether the call routes through Fleet or an external API.
    """

    rubric: Any  # str or Rubric
    submission: Optional[str] = None
    ground_truth: Optional[Union[str, dict]] = None
    problem: Optional[str] = None
    context: Optional[str] = None
    conversation: Optional[List[dict]] = None
    images: Optional[Dict[str, Any]] = None  # Dict[str, Image]
    files: Optional[Dict[str, Any]] = None  # Dict[str, File]
    model: Optional[str] = None
    provider: Optional[str] = None
    agentic: bool = False
    collect: Optional[Dict[str, List[str]]] = None
    task_id: Optional[str] = None
    instance_id: Optional[str] = None


@dataclass
class GradeResponse:
    """Provider-agnostic grading response.

    Normalized structure returned by all providers. Maps to the existing
    JudgeResult construction in ``_parse_grade_response``.
    """

    normalized_score: float
    total_score: float = 0.0
    max_score: float = 0.0
    criteria: List[dict] = field(default_factory=list)
    feedback: str = ""
    model_used: str = ""
    provider_used: str = ""
    accumulators: Optional[dict] = None
    raw: Optional[dict] = None  # Full raw response for pass-through

    def to_dict(self) -> dict:
        """Convert to dict matching the orchestrator response schema."""
        d: dict = {
            "normalized_score": self.normalized_score,
            "total_score": self.total_score,
            "max_score": self.max_score,
            "model_used": self.model_used,
            "provider_used": self.provider_used,
        }
        if self.criteria:
            d["criteria"] = self.criteria
        if self.feedback:
            d["feedback"] = self.feedback
        if self.accumulators:
            d["accumulators"] = self.accumulators
        return d


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class LLMProvider(ABC):
    """Abstract interface for LLM judge backends.

    Implementations must provide ``grade()`` (sync) and/or ``agrade()``
    (async). The judge classes call whichever variant matches their
    execution model.

    Providers can override ``resolve_image()`` / ``resolve_file()`` to
    customise how ``source="path"`` references are resolved (e.g. prepend
    an S3 prefix, fetch from GCS, etc.).  The default implementation
    auto-detects the URI scheme and delegates to the appropriate legacy
    constructor.
    """

    # ------------------------------------------------------------------
    # Path resolution (override for custom storage backends)
    # ------------------------------------------------------------------

    def resolve_image(self, image: Any) -> Any:
        """Resolve a path-based Image to a concrete source.

        Override in subclasses for custom resolution logic (e.g. prepending
        an S3 bucket prefix, fetching from GCS/Azure Blob, etc.).

        The default implementation auto-detects the URI scheme:

        - ``s3://``       → ``Image.s3()``
        - ``http(s)://``  → ``Image.from_url()``
        - anything else   → ``Image.from_local()``

        Non-path images are returned unchanged.
        """
        if getattr(image, "source", None) != "path":
            return image

        from .judge import Image as _Image

        path = image._path or image.filename or ""
        mt = image.media_type

        if path.startswith("s3://"):
            return _Image.s3(path, media_type=mt)
        elif path.startswith(("http://", "https://")):
            return _Image.from_url(path, media_type=mt)
        else:
            return _Image.from_local(path, media_type=mt)

    def resolve_file(self, file: Any) -> Any:
        """Resolve a path-based File to a concrete source.

        Same semantics as ``resolve_image()`` but for File objects.
        """
        if getattr(file, "source", None) != "path":
            return file

        from .judge import File as _File

        path = file._path or file.filename or ""
        mt = file.media_type

        if path.startswith("s3://"):
            return _File.s3(path, media_type=mt)
        else:
            return _File.from_local(path, media_type=mt)

    def resolve_images(self, images: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Resolve all path-based images in a dict."""
        if not images:
            return images
        return {label: self.resolve_image(img) for label, img in images.items()}

    def resolve_files(self, files: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Resolve all path-based files in a dict."""
        if not files:
            return files
        return {label: self.resolve_file(f) for label, f in files.items()}

    # ------------------------------------------------------------------
    # Grading (must implement)
    # ------------------------------------------------------------------

    @abstractmethod
    def grade(self, request: GradeRequest) -> GradeResponse:
        """Execute a synchronous grading call."""
        ...

    async def agrade(self, request: GradeRequest) -> GradeResponse:
        """Execute an asynchronous grading call.

        Default implementation calls the sync ``grade()`` method.
        Providers that support native async should override this.
        """
        return self.grade(request)


# ---------------------------------------------------------------------------
# Fleet orchestrator provider (default)
# ---------------------------------------------------------------------------


class FleetProvider(LLMProvider):
    """Routes judge calls through the Fleet orchestrator API.

    This is the default provider — it preserves the existing behavior where
    ``SyncJudge.grade()`` calls ``POST /v1/judge/grade`` on the orchestrator.
    """

    def __init__(self, client: Any, instance_id: str):
        self._client = client
        self._instance_id = instance_id

    def grade(self, request: GradeRequest) -> GradeResponse:
        from .judge import _build_grade_request

        body = _build_grade_request(
            self._instance_id,
            request.rubric,
            request.submission,
            ground_truth=request.ground_truth,
            problem=request.problem,
            context=request.context,
            conversation=request.conversation,
            images=request.images,
            files=request.files,
            model=request.model,
            provider=request.provider,
            agentic=request.agentic,
            collect=request.collect,
            task_id=request.task_id,
        )

        response = self._client.request("POST", "/v1/judge/grade", json=body)
        data = response.json()

        return GradeResponse(
            normalized_score=float(data.get("normalized_score", 0.0)),
            total_score=float(data.get("total_score", 0)),
            max_score=float(data.get("max_score", 0)),
            criteria=data.get("criteria", []),
            feedback=data.get("feedback", ""),
            model_used=data.get("model_used", ""),
            provider_used=data.get("provider_used", ""),
            accumulators=data.get("accumulators"),
            raw=data,
        )

    async def agrade(self, request: GradeRequest) -> GradeResponse:
        from .judge import _build_grade_request

        body = _build_grade_request(
            self._instance_id,
            request.rubric,
            request.submission,
            ground_truth=request.ground_truth,
            problem=request.problem,
            context=request.context,
            conversation=request.conversation,
            images=request.images,
            files=request.files,
            model=request.model,
            provider=request.provider,
            agentic=request.agentic,
            collect=request.collect,
            task_id=request.task_id,
        )

        response = await self._client.request("POST", "/v1/judge/grade", json=body)
        data = response.json()

        return GradeResponse(
            normalized_score=float(data.get("normalized_score", 0.0)),
            total_score=float(data.get("total_score", 0)),
            max_score=float(data.get("max_score", 0)),
            criteria=data.get("criteria", []),
            feedback=data.get("feedback", ""),
            model_used=data.get("model_used", ""),
            provider_used=data.get("provider_used", ""),
            accumulators=data.get("accumulators"),
            raw=data,
        )


# ---------------------------------------------------------------------------
# External provider (OpenRouter, Anthropic, etc.)
# ---------------------------------------------------------------------------

# Default system prompt for the judge when running externally
_DEFAULT_JUDGE_SYSTEM_PROMPT = """\
You are an expert judge evaluating a submission against a rubric.
You must evaluate the submission fairly and provide a score for each criterion.

Respond with a JSON object in this exact format:
{
  "criteria": [
    {
      "name": "<criterion name>",
      "score": <integer score>,
      "max_score": <max score>,
      "reasoning": "<brief explanation>"
    }
  ],
  "feedback": "<overall feedback>"
}

IMPORTANT: Respond ONLY with the JSON object. No markdown fences, no extra text."""


def _build_judge_user_message(request: GradeRequest) -> str:
    """Build the user message content for the judge LLM call."""
    from .judge import Rubric

    parts: List[str] = []

    # Problem statement
    if request.problem:
        parts.append(f"## Problem\n{request.problem}")

    # Rubric
    if isinstance(request.rubric, str):
        parts.append(f"## Rubric\n{request.rubric}")
    elif isinstance(request.rubric, Rubric):
        rubric_lines = []
        for c in request.rubric.criteria:
            rubric_lines.append(f"- **{c.name}** (max {c.max} points): {c._render_description()}")
        parts.append(f"## Rubric\n" + "\n".join(rubric_lines))

    # Ground truth
    if request.ground_truth:
        gt = request.ground_truth
        if isinstance(gt, dict):
            gt = json.dumps(gt, indent=2)
        parts.append(f"## Ground Truth / Expected Answer\n{gt}")

    # Context
    if request.context:
        parts.append(f"## Additional Context\n{request.context}")

    # Conversation history
    if request.conversation:
        conv_lines = []
        for msg in request.conversation:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            conv_lines.append(f"[{role}]: {content}")
        parts.append(f"## Conversation History\n" + "\n\n".join(conv_lines))

    # Submission
    if request.submission:
        parts.append(f"## Submission to Grade\n{request.submission}")
    else:
        parts.append("## Submission to Grade\n(No submission text provided)")

    return "\n\n".join(parts)


def _build_anthropic_messages(
    request: GradeRequest,
    system_prompt: str,
) -> tuple:
    """Build messages list for the Anthropic/OpenAI chat completions format.

    Returns (system_prompt, messages) tuple.
    """
    from .judge import Rubric

    # Use rubric's system_prompt override if provided
    if isinstance(request.rubric, Rubric) and request.rubric.system_prompt:
        system_prompt = request.rubric.system_prompt

    user_content: list = []

    # Add images as base64 content blocks (Anthropic vision format)
    if request.images:
        for label, img in request.images.items():
            # Resolve path-based images to base64 (fallback if not pre-resolved)
            if img.source == "path" and img._path:
                path = img._path
                if path.startswith(("http://", "https://")):
                    user_content.append({
                        "type": "image",
                        "source": {
                            "type": "url",
                            "url": path,
                        },
                    })
                else:
                    # Treat as local file
                    import base64 as _b64
                    try:
                        with open(path, "rb") as fh:
                            b64 = _b64.b64encode(fh.read()).decode("ascii")
                        user_content.append({
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": img.media_type or "image/png",
                                "data": b64,
                            },
                        })
                    except (OSError, IOError):
                        logger.warning("Skipping unreadable path image: %s", path)
                continue

            # Resolve local images to base64 first
            if img.source == "local" and img._local_path:
                b64 = img._resolve_local()
                if b64:
                    user_content.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": img.media_type or "image/png",
                            "data": b64,
                        },
                    })
                else:
                    logger.warning("Skipping unreadable local image: %s", img._local_path)
                continue

            if img.data:  # base64 data available
                user_content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": img.media_type or "image/png",
                        "data": img.data,
                    },
                })
            elif img.url:
                user_content.append({
                    "type": "image",
                    "source": {
                        "type": "url",
                        "url": img.url,
                    },
                })

    # Add text content
    user_text = _build_judge_user_message(request)
    user_content.append({"type": "text", "text": user_text})

    messages = [{"role": "user", "content": user_content}]
    return system_prompt, messages


def _parse_llm_judge_response(
    raw_text: str,
    rubric: Any,
    model: str,
    provider: str,
) -> GradeResponse:
    """Parse the LLM's JSON response into a GradeResponse."""
    from .judge import Rubric

    # Strip markdown fences if present
    text = raw_text.strip()
    if text.startswith("```"):
        # Remove opening fence (```json or ```)
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning("Failed to parse judge LLM response as JSON: %s", e)
        logger.debug("Raw response: %s", raw_text[:500])
        return GradeResponse(
            normalized_score=0.0,
            feedback=f"Failed to parse judge response: {e}",
            model_used=model,
            provider_used=provider,
        )

    criteria = data.get("criteria", [])
    feedback = data.get("feedback", "")

    # Compute scores
    total_score = sum(c.get("score", 0) for c in criteria)
    if isinstance(rubric, Rubric):
        max_score = rubric.max_score
    else:
        max_score = sum(c.get("max_score", 0) for c in criteria)

    normalized = total_score / max_score if max_score > 0 else 0.0

    return GradeResponse(
        normalized_score=normalized,
        total_score=float(total_score),
        max_score=float(max_score),
        criteria=criteria,
        feedback=feedback,
        model_used=model,
        provider_used=provider,
        raw=data,
    )


class ExternalProvider(LLMProvider):
    """Routes judge calls directly to an external LLM API.

    Supports any OpenAI-compatible chat completions endpoint, including:
    - OpenRouter (https://openrouter.ai/api/v1)
    - Anthropic via proxy
    - Azure OpenAI
    - Local models (vLLM, Ollama, etc.)

    Args:
        api_key: API key for the provider.
        base_url: Base URL for the chat completions API.
            Defaults to OpenRouter.
        model: Model identifier (e.g., "anthropic/claude-sonnet-4").
        system_prompt: Override the default judge system prompt.
        timeout: Request timeout in seconds (default: 300).
        extra_headers: Additional headers to include in requests.
        temperature: Sampling temperature (default: 0.0 for deterministic).
        max_tokens: Maximum tokens in response (default: 4096).

    Example::

        provider = ExternalProvider(
            api_key="sk-or-...",
            base_url="https://openrouter.ai/api/v1",
            model="anthropic/claude-sonnet-4",
        )
        judge = SyncJudge(client=None, instance_id="local", llm_provider=provider)
        result = judge.grade(rubric, submission)
    """

    DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
    DEFAULT_MODEL = "anthropic/claude-sonnet-4"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        system_prompt: Optional[str] = None,
        timeout: float = 300.0,
        extra_headers: Optional[Dict[str, str]] = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ):
        self.api_key = api_key
        self.base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self.model = model or self.DEFAULT_MODEL
        self.system_prompt = system_prompt or _DEFAULT_JUDGE_SYSTEM_PROMPT
        self.timeout = timeout
        self.extra_headers = extra_headers or {}
        self.temperature = temperature
        self.max_tokens = max_tokens

    def _get_headers(self) -> Dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        headers.update(self.extra_headers)
        return headers

    def _build_request_body(self, request: GradeRequest) -> dict:
        """Build an OpenAI-compatible chat completions request body."""
        model = request.model or self.model
        system_prompt, messages = _build_anthropic_messages(
            request, self.system_prompt,
        )

        # Convert to OpenAI chat format
        oai_messages: List[dict] = [
            {"role": "system", "content": system_prompt},
        ]
        for msg in messages:
            content = msg["content"]
            if isinstance(content, list):
                # Convert multimodal content blocks to OpenAI format
                oai_content: List[dict] = []
                for block in content:
                    if block.get("type") == "text":
                        oai_content.append({"type": "text", "text": block["text"]})
                    elif block.get("type") == "image":
                        source = block.get("source", {})
                        if source.get("type") == "base64":
                            oai_content.append({
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{source.get('media_type', 'image/png')};base64,{source['data']}",
                                },
                            })
                        elif source.get("type") == "url":
                            oai_content.append({
                                "type": "image_url",
                                "image_url": {"url": source["url"]},
                            })
                oai_messages.append({"role": msg["role"], "content": oai_content})
            else:
                oai_messages.append(msg)

        return {
            "model": model,
            "messages": oai_messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

    def grade(self, request: GradeRequest) -> GradeResponse:
        """Grade via external OpenAI-compatible API (sync)."""
        model = request.model or self.model
        body = self._build_request_body(request)
        url = f"{self.base_url}/chat/completions"

        start_ms = time.time() * 1000

        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(url, json=body, headers=self._get_headers())
            response.raise_for_status()

        elapsed_ms = time.time() * 1000 - start_ms
        data = response.json()

        # Extract response text from OpenAI format
        raw_text = data["choices"][0]["message"]["content"]

        result = _parse_llm_judge_response(
            raw_text, request.rubric, model, self.base_url,
        )
        result.accumulators = {"elapsed_ms": elapsed_ms}
        return result

    async def agrade(self, request: GradeRequest) -> GradeResponse:
        """Grade via external OpenAI-compatible API (async)."""
        model = request.model or self.model
        body = self._build_request_body(request)
        url = f"{self.base_url}/chat/completions"

        start_ms = time.time() * 1000

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, json=body, headers=self._get_headers())
            response.raise_for_status()

        elapsed_ms = time.time() * 1000 - start_ms
        data = response.json()

        # Extract response text from OpenAI format
        raw_text = data["choices"][0]["message"]["content"]

        result = _parse_llm_judge_response(
            raw_text, request.rubric, model, self.base_url,
        )
        result.accumulators = {"elapsed_ms": elapsed_ms}
        return result


# ---------------------------------------------------------------------------
# Auto-configuration from environment variables
# ---------------------------------------------------------------------------


def resolve_provider() -> Optional[LLMProvider]:
    """Build an LLM provider from environment variables.

    Reads ``FLEET_LLM_*`` env vars and returns an ``ExternalProvider`` when
    ``FLEET_LLM_API_KEY`` is set, otherwise returns ``None`` (meaning the
    caller should fall back to the Fleet orchestrator).

    Env vars::

        FLEET_LLM_API_KEY       (required to activate external routing)
        FLEET_LLM_BASE_URL      (default: https://openrouter.ai/api/v1)
        FLEET_LLM_MODEL         (default: anthropic/claude-sonnet-4)
        FLEET_LLM_TEMPERATURE   (default: 0.0)
        FLEET_LLM_MAX_TOKENS    (default: 4096)
        FLEET_LLM_TIMEOUT       (default: 300)

    Returns:
        An ``ExternalProvider`` if ``FLEET_LLM_API_KEY`` is set, else ``None``.
    """
    api_key = os.environ.get(ENV_LLM_API_KEY)
    if not api_key:
        return None

    base_url = os.environ.get(ENV_LLM_BASE_URL) or None
    model = os.environ.get(ENV_LLM_MODEL) or None

    temperature = 0.0
    temp_str = os.environ.get(ENV_LLM_TEMPERATURE)
    if temp_str:
        try:
            temperature = float(temp_str)
        except ValueError:
            logger.warning("Invalid %s=%r, using default 0.0", ENV_LLM_TEMPERATURE, temp_str)

    max_tokens = 4096
    mt_str = os.environ.get(ENV_LLM_MAX_TOKENS)
    if mt_str:
        try:
            max_tokens = int(mt_str)
        except ValueError:
            logger.warning("Invalid %s=%r, using default 4096", ENV_LLM_MAX_TOKENS, mt_str)

    timeout = 300.0
    to_str = os.environ.get(ENV_LLM_TIMEOUT)
    if to_str:
        try:
            timeout = float(to_str)
        except ValueError:
            logger.warning("Invalid %s=%r, using default 300", ENV_LLM_TIMEOUT, to_str)

    logger.info(
        "LLM provider configured from env: base_url=%s model=%s",
        base_url or ExternalProvider.DEFAULT_BASE_URL,
        model or ExternalProvider.DEFAULT_MODEL,
    )

    return ExternalProvider(
        api_key=api_key,
        base_url=base_url,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
    )
