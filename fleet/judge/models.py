"""Pydantic v2 models for the Fleet judge/grading system.

Self-contained data models with zero infrastructure dependencies.
Used by both the Fleet SDK (``Judge``) and the orchestrator.
"""

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Rubric types (discriminated union on `type`)
# ---------------------------------------------------------------------------


class StringRubric(BaseModel):
    type: Literal["string"] = "string"
    text: str


class Criterion(BaseModel):
    name: str
    description: str
    max_score: float


class StructuredRubric(BaseModel):
    type: Literal["structured"] = "structured"
    criteria: List[Criterion]


Rubric = Union[StringRubric, StructuredRubric]


# ---------------------------------------------------------------------------
# Image source types (discriminated union on `source`)
# ---------------------------------------------------------------------------


class S3ImageSource(BaseModel):
    source: Literal["s3"] = "s3"
    url: str  # s3://bucket/key
    media_type: Optional[str] = None
    label: Optional[str] = None


class Base64ImageSource(BaseModel):
    source: Literal["base64"] = "base64"
    data: str
    media_type: str  # e.g. "image/png"
    label: Optional[str] = None


class CollectImageSource(BaseModel):
    source: Literal["collect"] = "collect"
    selector: str
    label: Optional[str] = None


ImageSource = Union[S3ImageSource, Base64ImageSource, CollectImageSource]


# ---------------------------------------------------------------------------
# File source types (discriminated union on `source`)
# ---------------------------------------------------------------------------


class S3FileSource(BaseModel):
    source: Literal["s3"] = "s3"
    url: str
    media_type: Optional[str] = None
    label: Optional[str] = None


class Base64FileSource(BaseModel):
    source: Literal["base64"] = "base64"
    data: str
    filename: str
    media_type: str
    label: Optional[str] = None


class CollectFileSource(BaseModel):
    source: Literal["collect"] = "collect"
    selector: str
    label: Optional[str] = None


FileSource = Union[S3FileSource, Base64FileSource, CollectFileSource]


# ---------------------------------------------------------------------------
# Conversation message
# ---------------------------------------------------------------------------


class ConversationMessage(BaseModel):
    role: str
    content: str


# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------


class JudgeGradeRequest(BaseModel):
    submission: str
    rubric: Rubric = Field(..., discriminator="type")
    images: Optional[List[ImageSource]] = None
    files: Optional[List[FileSource]] = None
    ground_truth: Optional[str] = None
    problem: Optional[str] = None
    context: Optional[str] = None
    conversation: Optional[List[ConversationMessage]] = None
    model: Optional[str] = None
    agentic: bool = False
    instance_id: Optional[str] = None
    collect: Optional[Dict[str, Any]] = None
    task_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------


class CriterionResult(BaseModel):
    name: str
    score: float
    max_score: float
    reasoning: str


class JudgeGradeResponse(BaseModel):
    execution_id: str
    normalized_score: float  # 0-1 clamped
    total_score: float
    max_score: float
    criteria: Optional[List[CriterionResult]] = None
    feedback: str
    model_used: str
    provider_used: str = "anthropic"
    accumulators: Optional[Dict[str, Any]] = None
    artifacts_collected: Optional[Dict[str, Any]] = None
    raw_judge_response: Optional[str] = None
