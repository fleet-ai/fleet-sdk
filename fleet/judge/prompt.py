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

"""Prompt construction for LLM-as-a-judge grading.

Mirrors the orchestrator's ``build_structured_rubric_prompt`` logic from
``judge_service.py``.
"""

from typing import Any, Dict, List, Optional, Tuple

from fleet.judge.models import Rubric


def build_structured_rubric_prompt(
    rubric: Rubric,
    submission: str,
    ground_truth: Optional[str] = None,
    problem: Optional[str] = None,
    context: Optional[str] = None,
    conversation: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[str, str]:
    """Build system prompt and user message for structured rubric grading.

    Returns:
        A ``(system_prompt, user_message)`` tuple.
    """
    system_prompt = _build_system_prompt(rubric)
    user_message = _build_user_message(
        rubric=rubric,
        submission=submission,
        ground_truth=ground_truth,
        problem=problem,
        context=context,
        conversation=conversation,
    )
    return system_prompt, user_message


def _build_system_prompt(rubric: Rubric) -> str:
    criteria_descriptions = []
    for criterion in rubric.criteria:
        desc = f"### {criterion.name} (max {criterion.max_score} points)\n"
        if criterion.levels:
            for score in sorted(criterion.levels.keys(), reverse=True):
                desc += f"- **{score}**: {criterion.levels[score]}\n"
        elif criterion.description:
            desc += f"{criterion.description}\n"
        criteria_descriptions.append(desc)

    criteria_block = "\n".join(criteria_descriptions)

    criteria_json_items = []
    for c in rubric.criteria:
        criteria_json_items.append(
            f'    {{"name": "{c.name}", "score": <number 0-{c.max_score}>, '
            f'"reasoning": "<brief justification>"}}'
        )
    criteria_json = ",\n".join(criteria_json_items)

    return f"""\
You are an expert evaluator. You will grade a submission using a structured rubric.

## Rubric

{criteria_block}

## Instructions

1. Carefully read the submission and any provided ground truth, problem statement, or context.
2. Evaluate the submission against EACH criterion in the rubric.
3. For each criterion, assign a score within the allowed range and provide brief reasoning.
4. Provide overall feedback summarizing the evaluation.

## Response Format

You MUST respond with valid JSON in exactly this format:

```json
{{
  "criteria": [
{criteria_json}
  ],
  "feedback": "<overall feedback summarizing the evaluation>"
}}
```

Do not include any text outside the JSON response."""


def _build_user_message(
    rubric: Rubric,
    submission: str,
    ground_truth: Optional[str] = None,
    problem: Optional[str] = None,
    context: Optional[str] = None,
    conversation: Optional[List[Dict[str, Any]]] = None,
) -> str:
    parts: List[str] = []

    if problem:
        parts.append(f"## Problem\n\n{problem}")

    if context:
        parts.append(f"## Context\n\n{context}")

    if ground_truth:
        parts.append(f"## Ground Truth / Expected Answer\n\n{ground_truth}")

    if conversation:
        conv_lines = []
        for msg in conversation:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            conv_lines.append(f"**{role}**: {content}")
        parts.append("## Conversation\n\n" + "\n\n".join(conv_lines))

    parts.append(f"## Submission\n\n{submission}")

    return "\n\n".join(parts)
