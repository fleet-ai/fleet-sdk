"""Fleet SDK Judge - LLM-as-Judge grading via orchestrator API.

Provides env.judge.grade() for verifier scripts to grade submissions
using LLM judges without managing API keys, HTTP calls, or response parsing.

All LLM calls happen server-side on the orchestrator — the SDK just sends
the rubric, submission, and artifacts, and gets back a score.
"""

import base64
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union, TYPE_CHECKING

if TYPE_CHECKING:
    from .base import SyncWrapper

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes (used by both sync and async)
# ---------------------------------------------------------------------------


def _guess_media_type(filename: str) -> str:
    """Guess media type from filename extension."""
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    return {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "webp": "image/webp",
        "svg": "image/svg+xml",
    }.get(ext, "image/png")


@dataclass
class Criterion:
    """A single rubric criterion for grading.

    Args:
        name: Name of this criterion (e.g., "Takeaway Alignment")
        max: Maximum points for this criterion
        levels: Optional mapping of score -> description for each level.
            Rendered into the description string for the API.
        description: Optional freeform description (alternative to levels)
    """

    name: str
    max: int
    levels: Optional[Dict[int, str]] = None
    description: Optional[str] = None

    def _render_description(self) -> str:
        """Render levels dict + description into a single description string."""
        parts = []
        if self.levels:
            for score in sorted(self.levels.keys(), reverse=True):
                parts.append(f"- {score} points: {self.levels[score]}")
        if self.description:
            parts.append(self.description)
        return "\n".join(parts) if parts else self.name

    def serialize(self) -> dict:
        return {
            "name": self.name,
            "max_score": self.max,
            "description": self._render_description(),
        }


@dataclass
class Rubric:
    """Structured grading rubric.

    Args:
        criteria: List of Criterion objects
        system_prompt: Optional override for the judge system prompt
    """

    criteria: List[Criterion] = field(default_factory=list)
    system_prompt: Optional[str] = None

    @property
    def max_score(self) -> int:
        return sum(c.max for c in self.criteria)

    def serialize(self) -> dict:
        d: dict = {
            "type": "structured",
            "criteria": [c.serialize() for c in self.criteria],
        }
        if self.system_prompt is not None:
            d["system_prompt"] = self.system_prompt
        return d


class Image:
    """Reference to an image for LLM judge grading.

    Use the static constructors to create instances:
        Image.s3("s3://bucket/key")           - S3 URL, fetched server-side
        Image.from_url("https://...")          - HTTP URL, fetched server-side
        Image.from_base64(data, "file.png")    - Inline base64 data
        Image.from_env(env, "plot.png")        - Collect from environment
    """

    def __init__(
        self,
        *,
        source: str,
        url: Optional[str] = None,
        data: Optional[str] = None,
        filename: Optional[str] = None,
        media_type: Optional[str] = None,
        _env: Optional[Any] = None,
    ):
        self.source = source
        self.url = url
        self.data = data
        self.filename = filename
        self.media_type = media_type
        self._env = _env

    @staticmethod
    def s3(url: str, media_type: Optional[str] = None) -> "Image":
        """Reference an image in S3. The orchestrator fetches it server-side."""
        return Image(source="s3", url=url, media_type=media_type)

    @staticmethod
    def from_url(url: str, media_type: Optional[str] = None) -> "Image":
        """Reference an image by HTTP URL. The orchestrator fetches it server-side."""
        return Image(source="url", url=url, media_type=media_type)

    @staticmethod
    def from_base64(
        data: str, filename: str = "image.png", media_type: Optional[str] = None
    ) -> "Image":
        """Inline base64 image data."""
        return Image(
            source="base64",
            data=data,
            filename=filename,
            media_type=media_type or _guess_media_type(filename),
        )

    @staticmethod
    def from_env(env: Any, filename: str) -> "Image":
        """Collect an image from the environment.

        In non-agentic mode, the SDK collects the image client-side (DB -> notebook -> filesystem)
        and sends base64 to the orchestrator.

        In agentic mode, only the filename hint is sent and the orchestrator collects it.
        """
        return Image(source="env", filename=filename, _env=env)

    def serialize(self, *, label: Optional[str] = None, agentic: bool = False) -> dict:
        """Serialize for the orchestrator API request body."""
        d: dict
        if self.source == "s3":
            d = {"source": "s3", "url": self.url}
            if self.media_type:
                d["media_type"] = self.media_type
        elif self.source == "url":
            d = {"source": "url", "url": self.url}
            if self.media_type:
                d["media_type"] = self.media_type
        elif self.source == "base64":
            d = {
                "source": "base64",
                "data": self.data,
                "media_type": self.media_type or _guess_media_type(self.filename or "image.png"),
            }
        elif self.source == "collect":
            d = {"source": "collect", "selector": self.filename}
        elif self.source == "env":
            if agentic:
                d = {"source": "collect", "selector": self.filename}
            else:
                b64 = _collect_image_from_env(self._env, self.filename)
                if b64 is None:
                    d = {"source": "collect", "selector": self.filename}
                else:
                    d = {
                        "source": "base64",
                        "data": b64,
                        "media_type": _guess_media_type(self.filename or "image.png"),
                    }
        else:
            raise ValueError(f"Unknown image source: {self.source}")

        if label is not None:
            d["label"] = label
        return d


class JudgeResult(float):
    """Float subclass that carries grading details.

    Can be returned directly from a verifier function (it IS a float),
    but also carries structured metadata from the judge response.
    """

    def __new__(cls, score: float, *, details: Optional[dict] = None):
        instance = super().__new__(cls, score)
        instance.details = details or {}  # type: ignore[attr-defined]
        instance.criteria = instance.details.get("criteria", [])  # type: ignore[attr-defined]
        instance.feedback = instance.details.get("feedback", "")  # type: ignore[attr-defined]
        instance.execution_id = instance.details.get("execution_id", "")  # type: ignore[attr-defined]
        return instance


# ---------------------------------------------------------------------------
# Image collection helpers
# ---------------------------------------------------------------------------


def _extract_query_rows(result: Any) -> List[Dict[str, Any]]:
    """Extract rows from a query response, handling various formats."""
    if result is None:
        return []
    # QueryResponse with columns/rows
    cols = getattr(result, "columns", None)
    rows = getattr(result, "rows", None)
    if isinstance(cols, list) and isinstance(rows, list):
        return [
            {str(cols[i]): row[i] for i in range(min(len(cols), len(row)))}
            if isinstance(row, (list, tuple))
            else row
            for row in rows
            if isinstance(row, (list, tuple, dict))
        ]
    # Dict with columns/rows
    if isinstance(result, dict):
        cols = result.get("columns")
        rows = result.get("rows")
        if isinstance(cols, list) and isinstance(rows, list):
            return [
                {str(cols[i]): row[i] for i in range(min(len(cols), len(row)))}
                if isinstance(row, (list, tuple))
                else row
                for row in rows
                if isinstance(row, (list, tuple, dict))
            ]
    # Plain list of dicts
    if isinstance(result, list):
        return [row for row in result if isinstance(row, dict)]
    return []


def _collect_image_from_env(env: Any, filename: str) -> Optional[str]:
    """Collect an image from the environment using DB -> notebook -> filesystem strategies.

    Returns base64-encoded image data, or None if not found.
    """
    # Strategy 1: DB files table
    try:
        current = env.db("current")
        where = f"path = '{filename}' OR path LIKE '%/{filename}'"
        rows = _extract_query_rows(
            current.query(f"SELECT path, hex(content) AS content_hex FROM files WHERE {where}")
        )
        candidates = {}
        for row in rows:
            path, chex = row.get("path", ""), row.get("content_hex", "")
            if path and chex:
                try:
                    candidates[path] = bytes.fromhex(chex)
                except Exception:
                    pass
        # Prefer non-dataroom paths
        non_dr = [p for p in candidates if not p.startswith("dataroom/")]
        best = sorted(non_dr or list(candidates.keys()), key=len)
        if best:
            logger.debug("Loaded image from DB: %s", best[0])
            return base64.b64encode(candidates[best[0]]).decode()
    except Exception as e:
        logger.debug("DB image query failed: %s", e)

    # Strategy 2: Notebook cell outputs
    try:
        current = env.db("current")
        nb_rows = _extract_query_rows(
            current.query(
                "SELECT path, hex(content) AS content_hex FROM files "
                "WHERE path LIKE 'notebooks/%.ipynb'"
            )
        )
        for nb_row in nb_rows:
            chex = nb_row.get("content_hex", "")
            if not chex:
                continue
            try:
                nb_bytes = bytes.fromhex(chex)
                nb = json.loads(nb_bytes.decode("utf-8"))
                for cell in reversed(nb.get("cells", [])):
                    for output in cell.get("outputs", []):
                        if output.get("output_type") in ("display_data", "execute_result"):
                            img_data = output.get("data", {}).get("image/png")
                            if img_data:
                                if isinstance(img_data, list):
                                    img_data = "".join(img_data)
                                img_data = img_data.strip()
                                if img_data:
                                    logger.debug("Loaded image from notebook: %s", nb_row.get("path"))
                                    return img_data
            except Exception:
                pass
    except Exception as e:
        logger.debug("Notebook image query failed: %s", e)

    # Strategy 3: Filesystem fallback
    search_paths = [
        filename,
        f"/app/workspace/{filename}",
        f"/workspace/{filename}",
    ]
    for fp in search_paths:
        try:
            if os.path.exists(fp):
                with open(fp, "rb") as f:
                    logger.debug("Loaded image from filesystem: %s", fp)
                    return base64.b64encode(f.read()).decode()
        except Exception:
            pass

    return None


async def _collect_image_from_env_async(env: Any, filename: str) -> Optional[str]:
    """Async version of _collect_image_from_env.

    Collects an image from an AsyncEnv using DB -> notebook -> filesystem strategies.
    Returns base64-encoded image data, or None if not found.
    """
    # Strategy 1: DB files table
    try:
        current = env.db("current")
        where = f"path = '{filename}' OR path LIKE '%/{filename}'"
        rows = _extract_query_rows(
            await current.query(f"SELECT path, hex(content) AS content_hex FROM files WHERE {where}")
        )
        candidates = {}
        for row in rows:
            path, chex = row.get("path", ""), row.get("content_hex", "")
            if path and chex:
                try:
                    candidates[path] = bytes.fromhex(chex)
                except Exception:
                    pass
        # Prefer non-dataroom paths
        non_dr = [p for p in candidates if not p.startswith("dataroom/")]
        best = sorted(non_dr or list(candidates.keys()), key=len)
        if best:
            logger.debug("Loaded image from DB (async): %s", best[0])
            return base64.b64encode(candidates[best[0]]).decode()
    except Exception as e:
        logger.debug("DB image query failed (async): %s", e)

    # Strategy 2: Notebook cell outputs
    try:
        current = env.db("current")
        nb_rows = _extract_query_rows(
            await current.query(
                "SELECT path, hex(content) AS content_hex FROM files "
                "WHERE path LIKE 'notebooks/%.ipynb'"
            )
        )
        for nb_row in nb_rows:
            chex = nb_row.get("content_hex", "")
            if not chex:
                continue
            try:
                nb_bytes = bytes.fromhex(chex)
                nb = json.loads(nb_bytes.decode("utf-8"))
                for cell in reversed(nb.get("cells", [])):
                    for output in cell.get("outputs", []):
                        if output.get("output_type") in ("display_data", "execute_result"):
                            img_data = output.get("data", {}).get("image/png")
                            if img_data:
                                if isinstance(img_data, list):
                                    img_data = "".join(img_data)
                                img_data = img_data.strip()
                                if img_data:
                                    logger.debug("Loaded image from notebook (async): %s", nb_row.get("path"))
                                    return img_data
            except Exception:
                pass
    except Exception as e:
        logger.debug("Notebook image query failed (async): %s", e)

    # Strategy 3: Filesystem fallback
    search_paths = [
        filename,
        f"/app/workspace/{filename}",
        f"/workspace/{filename}",
    ]
    for fp in search_paths:
        try:
            if os.path.exists(fp):
                with open(fp, "rb") as f:
                    logger.debug("Loaded image from filesystem (async): %s", fp)
                    return base64.b64encode(f.read()).decode()
        except Exception:
            pass

    return None


# ---------------------------------------------------------------------------
# Accumulator printing (verifier protocol)
# ---------------------------------------------------------------------------


def _print_accumulators(data: dict) -> None:
    """Print error/success accumulators from orchestrator response (verifier protocol)."""
    acc = data.get("accumulators")
    if not acc:
        return

    errors = acc.get("errors")
    if errors:
        print("[STDOUT] >>> ERROR_ACCUMULATOR >>>")
        print(json.dumps(errors))
        print("<<< ERROR_ACCUMULATOR <<<")

    successes = acc.get("successes")
    if successes:
        print(">>> SUCCESS_ACCUMULATOR >>>")
        print(json.dumps(successes))
        print("<<< SUCCESS_ACCUMULATOR <<<")

    grading_details = acc.get("grading_details")
    if grading_details:
        print(">>> GRADING_DETAILS >>>")
        print(json.dumps(grading_details))
        print("<<< GRADING_DETAILS <<<")

    golden_urls = acc.get("golden_urls")
    if golden_urls:
        print(">>> GOLDEN_URLS >>>")
        print(json.dumps(golden_urls))
        print("<<< GOLDEN_URLS <<<")

    timing = acc.get("timing")
    if timing:
        print(
            f">>> TIMING: started={timing.get('started_ms')}, "
            f"finished={timing.get('finished_ms')}, "
            f"duration={timing.get('duration_ms')}ms <<<"
        )


# ---------------------------------------------------------------------------
# Request body builder (shared by sync and async)
# ---------------------------------------------------------------------------


def _print_judge_call_start(
    rubric: Union[str, "Rubric"],
    images: Optional[Dict[str, "Image"]],
    agentic: bool,
    model: Optional[str],
) -> None:
    """Print info when initiating a judge grading call."""
    mode = "agentic" if agentic else "standard"
    model_str = model or "default"
    print(f"[C] Calling judge ({mode} mode, model={model_str})")

    if isinstance(rubric, Rubric):
        criteria_names = [c.name for c in rubric.criteria]
        print(f"[C] Rubric: {len(rubric.criteria)} criteria ({', '.join(criteria_names)}), max={rubric.max_score}")

    if images:
        for label, img in images.items():
            src = img.source
            detail = ""
            if img.url:
                detail = f" url={img.url}"
            elif img.filename:
                detail = f" file={img.filename}"
            print(f"[C] Image '{label}': source={src}{detail}")
    else:
        print("[C] No images provided")


def _build_grade_request(
    instance_id: str,
    rubric: Union[str, Rubric],
    submission: Optional[str],
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
) -> dict:
    """Build the JSON request body for POST /v1/judge/grade."""
    body: Dict[str, Any] = {
        "instance_id": instance_id,
        "submission": submission,
        "agentic": agentic,
    }

    # Rubric
    if isinstance(rubric, str):
        body["rubric"] = {"type": "string", "text": rubric}
    elif isinstance(rubric, Rubric):
        body["rubric"] = rubric.serialize()
    else:
        raise TypeError(f"rubric must be str or Rubric, got {type(rubric)}")

    # Optional fields
    if ground_truth is not None:
        body["ground_truth"] = ground_truth
    if problem is not None:
        body["problem"] = problem
    if reference_claims is not None:
        # Fold reference_claims into context
        if context:
            context = f"{context}\n\n## Reference Claims\n{reference_claims}"
        else:
            context = f"## Reference Claims\n{reference_claims}"
    if context is not None:
        body["context"] = context
    if conversation is not None:
        body["conversation"] = [
            {"role": m["role"], "content": m["content"]} for m in conversation
        ]
    if model is not None:
        body["model"] = model
    if provider is not None:
        body["provider"] = provider
    if task_id is not None:
        body["task_id"] = task_id
    if collect is not None:
        body["collect"] = collect

    # Serialize images as labeled array
    if images:
        body["images"] = [
            img.serialize(label=label, agentic=agentic)
            for label, img in images.items()
        ]

    return body


def _parse_grade_response(data: dict) -> JudgeResult:
    """Parse orchestrator response into JudgeResult and print accumulators."""
    # Print detailed judge grading info
    _print_judge_result(data)
    _print_accumulators(data)
    score = float(data.get("normalized_score", 0.0))
    return JudgeResult(score, details=data)


def _print_judge_result(data: dict) -> None:
    """Print detailed judge grading result for verifier stdout capture."""
    model = data.get("model_used", "unknown")
    provider = data.get("provider_used", "unknown")
    total = data.get("total_score", 0)
    max_score = data.get("max_score", 0)
    normalized = data.get("normalized_score", 0)
    elapsed = (data.get("accumulators") or {}).get("elapsed_ms")

    print(f"[C] Grading via {model} (provider={provider})")
    if elapsed is not None:
        print(f"[C] Judge call completed in {elapsed:.0f}ms")

    criteria = data.get("criteria")
    if criteria:
        print(f"[C] Score: {total}/{max_score} ({normalized:.2f})")
        for c in criteria:
            name = c.get("name", "?")
            cscore = c.get("score", "?")
            cmax = c.get("max_score", "?")
            reasoning = c.get("reasoning", "")
            # Truncate long reasoning for stdout readability
            if len(reasoning) > 200:
                reasoning = reasoning[:200] + "..."
            print(f"[C]   {name}: {cscore}/{cmax} — {reasoning}")
    else:
        print(f"[C] Score: {normalized:.2f}")

    feedback = data.get("feedback")
    if feedback:
        fb_display = feedback if len(feedback) <= 300 else feedback[:300] + "..."
        print(f"[C] Feedback: {fb_display}")

    # Print golden URLs if present in accumulators
    golden_urls = (data.get("accumulators") or {}).get("golden_urls")
    if golden_urls:
        for url in golden_urls:
            print(f"[C] Gold reference: {url}")


# ---------------------------------------------------------------------------
# Sync judge
# ---------------------------------------------------------------------------


class SyncJudge:
    """LLM-as-judge grading — calls orchestrator API, not environment API.

    Accessed as env.judge on SyncEnv instances.
    """

    def __init__(self, client: "SyncWrapper", instance_id: str):
        self._client = client
        self._instance_id = instance_id

    def grade(
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
            reference_claims: Reference analysis claims (folded into context).
            conversation: Conversation history as list of message dicts.
            images: List of Image objects for the judge.
            model: Override LLM model (server picks default if None).
            provider: Override LLM provider (server picks default if None).
            agentic: If True, the orchestrator collects artifacts from the instance.
            collect: File patterns for orchestrator to collect (agentic mode).
            task_id: Optional task ID for tracking.
        """
        body = _build_grade_request(
            self._instance_id,
            rubric,
            submission,
            ground_truth=ground_truth,
            problem=problem,
            context=context,
            reference_claims=reference_claims,
            conversation=conversation,
            images=images,
            model=model,
            provider=provider,
            agentic=agentic,
            collect=collect,
            task_id=task_id,
        )

        _print_judge_call_start(rubric, images, agentic, model)
        response = self._client.request("POST", "/v1/judge/grade", json=body)
        return _parse_grade_response(response.json())
