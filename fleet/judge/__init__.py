"""Fleet Judge — LLM-based evaluation framework.

The core type is ``Judge``, an abstract base class that provides
evaluation infrastructure (LLM calls, agentic MCP tool-use, JSON
parsing, response normalization).  Subclasses implement
``build_prompt()`` to define the evaluation strategy.

This module does **not** include any rubric implementation.
Rubric-specific judges are defined by the orchestrator or by users.

Usage::

    from fleet.judge import Judge
    from fleet.judge.models import JudgeGradeRequest, StringRubric

    class MyJudge(Judge):
        def build_prompt(self, request, image_blocks, file_blocks):
            system = "You are an expert evaluator..."
            user = [{"type": "text", "text": request.submission}]
            return system, user

    judge = MyJudge(api_key="sk-ant-...")
    response = await judge.evaluate(
        JudgeGradeRequest(
            submission="Hello world",
            rubric=StringRubric(text="Grade quality"),
        ),
    )
"""

from .judge import (
    Judge,
    McpClient,
    ProgressCallback,
    build_grade_response,
    extract_json_from_response,
    resolve_base64_images,
    resolve_model,
)
from .models import (
    Base64FileSource,
    Base64ImageSource,
    CollectFileSource,
    CollectImageSource,
    ConversationMessage,
    Criterion,
    CriterionResult,
    FileSource,
    ImageSource,
    JudgeGradeRequest,
    JudgeGradeResponse,
    Rubric,
    S3FileSource,
    S3ImageSource,
    StringRubric,
    StructuredRubric,
)

__all__ = [
    # Core type
    "Judge",
    # Utilities
    "McpClient",
    "ProgressCallback",
    "build_grade_response",
    "extract_json_from_response",
    "resolve_base64_images",
    "resolve_model",
    # Models
    "Base64FileSource",
    "Base64ImageSource",
    "CollectFileSource",
    "CollectImageSource",
    "ConversationMessage",
    "Criterion",
    "CriterionResult",
    "FileSource",
    "ImageSource",
    "JudgeGradeRequest",
    "JudgeGradeResponse",
    "Rubric",
    "S3FileSource",
    "S3ImageSource",
    "StringRubric",
    "StructuredRubric",
]
