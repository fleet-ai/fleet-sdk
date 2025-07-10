import traceback
import logging
from typing import Any, Dict
from .db import DatabaseSnapshot, IgnoreConfig


logger = logging.getLogger(__name__)


TASK_SUCCESSFUL_SCORE = 1


def extract_last_assistant_message(transcript: str) -> str:
    """
    Extract only the last assistant message from the transcript, filtering out tool calls.

    Args:
        transcript: The full conversation transcript

    Returns:
        The content of the last assistant message with tool calls filtered out
    """
    if not transcript:
        return ""

    # Split transcript into sections by "Assistant:" markers
    sections = transcript.split("Assistant:")
    if len(sections) < 2:
        # No "Assistant:" markers found, treat entire transcript as assistant message
        last_assistant_section = transcript
    else:
        # Get the last assistant section
        last_assistant_section = sections[-1]

    # Filter out specific content blocks using regex-like approach
    import re

    # Remove image blocks: <img src="data:..."/>
    last_assistant_section = re.sub(
        r'<img src="data:[^"]*"[^>]*/?>', "", last_assistant_section
    )

    # Remove tool call blocks:  .../>
    last_assistant_section = re.sub(
        r'<tool_call[^>]*>.*?"/>', "", last_assistant_section, flags=re.DOTALL
    )

    # Remove tool result blocks: <tool_result>...</tool_result>
    last_assistant_section = re.sub(
        r"<tool_result>.*?</tool_result>", "", last_assistant_section, flags=re.DOTALL
    )

    # Clean up extra whitespace
    filtered_transcript = last_assistant_section.strip()

    return filtered_transcript


async def execute_validation_function(
    function_code: str,
    function_name: str,
    before_snapshot_path: str,
    after_snapshot_path: str,
    transcript: str | None = None,
) -> Dict[str, Any]:
    """
    Execute arbitrary validation function code with database snapshots.

    Args:
        function_code: The Python code containing the function definition
        function_name: Name of the function to call after executing the code
        before_snapshot_path: Path to the before database snapshot
        after_snapshot_path: Path to the after database snapshot

    Returns:
        Dict containing success status, result, and any error message
    """
    try:
        # Create database snapshots
        before = DatabaseSnapshot(before_snapshot_path)
        after = DatabaseSnapshot(after_snapshot_path)

        # Create a namespace with the required imports and constants
        namespace = {
            "DatabaseSnapshot": DatabaseSnapshot,
            "IgnoreConfig": IgnoreConfig,
            "TASK_SUCCESSFUL_SCORE": TASK_SUCCESSFUL_SCORE,
            "extract_last_assistant_message": extract_last_assistant_message,
            "__builtins__": __builtins__,
        }

        # Execute the provided code in the namespace
        exec(function_code, namespace)

        # Check if the function exists in the namespace
        if function_name not in namespace:
            return {
                "success": False,
                "error": f"Function '{function_name}' not found in the provided code",
                "result": None,
            }

        # Get the function from the namespace
        func = namespace[function_name]

        # Call the function with before/after snapshots
        # Support both sync and async functions
        import inspect

        # Check the function signature to determine how many arguments it accepts
        sig = inspect.signature(func)
        param_count = len(sig.parameters)

        if inspect.iscoroutinefunction(func):
            # Handle async function - we can await it since we're now async
            if param_count >= 3:
                result = await func(before, after, transcript)
            else:
                result = await func(before, after)
        else:
            # Handle sync function
            if param_count >= 3:
                result = func(before, after, transcript)
            else:
                result = func(before, after)

        return {"success": True, "result": result, "error": None}

    except Exception as e:
        error_msg = f"Error executing function: {str(e)}\n{traceback.format_exc()}"
        logger.error(error_msg)
        return {"success": False, "error": error_msg, "result": None}
