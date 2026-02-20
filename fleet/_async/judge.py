"""Fleet SDK Judge - Async version.

Provides env.judge.grade() for async verifier scripts.
"""

from typing import Dict, List, Optional, Union, TYPE_CHECKING

# Import shared classes and helpers from the sync module
from ..judge import (
    Criterion,
    Image,
    JudgeResult,
    Rubric,
    _build_grade_request,
    _collect_image_from_env_async,
    _guess_media_type,
    _parse_grade_response,
)

if TYPE_CHECKING:
    from .base import AsyncWrapper

# Re-export data classes so `from fleet._async.judge import ...` works
__all__ = [
    "AsyncJudge",
    "Criterion",
    "Image",
    "JudgeResult",
    "Rubric",
]


class AsyncJudge:
    """LLM-as-judge grading — calls orchestrator API, not environment API.

    Accessed as env.judge on AsyncEnv instances.
    """

    def __init__(self, client: "AsyncWrapper", instance_id: str):
        self._client = client
        self._instance_id = instance_id

    async def grade(
        self,
        rubric: Union[str, Rubric],
        submission: Optional[str] = None,
        *,
        ground_truth: Optional[Union[str, dict]] = None,
        problem: Optional[str] = None,
        context: Optional[str] = None,
        reference_claims: Optional[str] = None,
        conversation: Optional[List[dict]] = None,
        images: Optional[Dict[str, Image]] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        agentic: bool = False,
        collect: Optional[Dict[str, List[str]]] = None,
        task_id: Optional[str] = None,
    ) -> JudgeResult:
        """Grade a submission using LLM-as-judge via the orchestrator API.

        Returns a JudgeResult (float subclass with .details, .criteria, .feedback)
        that can be returned directly from a verifier function.

        Args:
            rubric: Grading rubric — either a string or a structured Rubric object.
            submission: The agent's final answer / submission text.
            ground_truth: Expected answer (string or dict).
            problem: The original problem statement.
            context: Additional context for the judge.
            reference_claims: Reference analysis claims.
            conversation: Conversation history as list of message dicts.
            images: Named images for the judge (e.g., gold reference, agent output).
            model: Override LLM model (server picks default if None).
            provider: Override LLM provider (server picks default if None).
            agentic: If True, the orchestrator collects artifacts from the instance.
            collect: File patterns for orchestrator to collect (agentic mode).
            task_id: Optional task ID for tracking.
        """
        # Resolve Image.from_env images asynchronously before building request
        resolved_images = images
        if images and not agentic:
            resolved_images = {}
            for label, img in images.items():
                if img.source == "env" and img._env is not None:
                    b64 = await _collect_image_from_env_async(img._env, img.filename)
                    if b64 is not None:
                        resolved_images[label] = Image.from_base64(
                            b64,
                            img.filename or "image.png",
                            _guess_media_type(img.filename or "image.png"),
                        )
                    else:
                        # Async collection failed — use collect source directly
                        # (don't keep the env image or serialize() will retry sync)
                        resolved_images[label] = Image(
                            source="collect",
                            filename=img.filename,
                        )
                else:
                    resolved_images[label] = img

        body = _build_grade_request(
            self._instance_id,
            rubric,
            submission,
            ground_truth=ground_truth,
            problem=problem,
            context=context,
            reference_claims=reference_claims,
            conversation=conversation,
            images=resolved_images,
            model=model,
            provider=provider,
            agentic=agentic,
            collect=collect,
            task_id=task_id,
        )

        response = await self._client.request("POST", "/v1/judge/grade", json=body)
        return _parse_grade_response(response.json())
