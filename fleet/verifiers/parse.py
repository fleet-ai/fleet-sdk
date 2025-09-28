import re


from typing import Optional


def extract_function_name(function_code: str) -> Optional[str]:
    """
    Extract function name from Python function code.

    Handles both regular functions (def) and async functions (async def).

    Args:
        function_code: Python function code as a string

    Returns:
        The function name if found, None otherwise
    """
    # Normalize escaped newlines and strip common Markdown code fences
    code = function_code.replace("\\n", "\n").strip()

    if "```" in code:
        # Extract the first fenced block if present
        fence_blocks = re.findall(r"```[a-zA-Z0-9_+-]*\n([\s\S]*?)\n```", code)
        if fence_blocks:
            code = fence_blocks[0].strip()

    # Remove leading decorators (keep them for regex but allow preceding lines)
    # Robust regex: allow optional decorators and whitespace before the def
    pattern = r"^\s*(?:@[\w\.\n+() ,]*\n\s*)*(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\("
    match = re.search(pattern, code, flags=re.MULTILINE)
    if match:
        return match.group(1)

    # Fallback: search anywhere (not anchored) for a def signature
    fallback = r"(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\("
    match = re.search(fallback, code)
    if match:
        return match.group(1)

    return None


def convert_verifier_string(verifier_str: str) -> str:
    """
    Convert a verifier function string from the old format (env: Environment)
    to the new format (before: DatabaseSnapshot, after: DatabaseSnapshot).

    Args:
        verifier_str: The original verifier function as a string

    Returns:
        The converted verifier function string
    """
    # First, handle escaped newlines in the input
    verifier_str = verifier_str.replace("\\n", "\n")

    # Extract function name, docstring, and body
    # More flexible pattern that accepts both int and float return types
    func_pattern = r'def\s+(\w+)\s*\(\s*env(?:\s*:\s*Environment)?\s*,?\s*final_answer(?:\s*:\s*str\s*\|\s*None)?\s*(?:=\s*None)?\s*\)\s*->\s*(?:float|int):\s*\n((?:\s*""".*?"""\s*\n)?)(.*)'
    match = re.match(func_pattern, verifier_str.strip(), re.DOTALL)

    if not match:
        # Try with multiline pattern
        func_pattern_multiline = r'def\s+(\w+)\s*\(\s*\n?\s*env(?:\s*:\s*Environment)?\s*,?\s*\n?\s*final_answer(?:\s*:\s*str\s*\|\s*None)?\s*(?:=\s*None)?\s*\n?\s*\)\s*->\s*(?:float|int):\s*\n((?:\s*""".*?"""\s*\n)?)(.*)'
        match = re.match(func_pattern_multiline, verifier_str.strip(), re.DOTALL)

        if not match:
            raise ValueError(
                "Could not parse verifier function. Expected format: def function_name(env: Environment, final_answer: Optional[str] = None) -> float/int:"
            )

    func_name = match.group(1)
    docstring = match.group(2).strip()
    body = match.group(3)

    # Find all unique env.db() calls
    db_calls = re.findall(r'env\.db\("(\w+)"\)', body)
    unique_db_names = list(
        dict.fromkeys(db_calls)
    )  # Remove duplicates while preserving order

    # Build the new function
    new_func = f"""def {func_name}(
    before: DatabaseSnapshot, after: DatabaseSnapshot, transcript: Optional[str] = None
) -> int:
    class Environment:
        def db(self, name: str) -> DatabaseSnapshot:"""

    # Build the db method based on found database names
    if unique_db_names:
        conditions = []
        for db_name in unique_db_names:
            if db_name == "seed":
                conditions.append('before if name == "seed"')
            elif db_name == "current":
                conditions.append("after")
            else:
                # Handle other database names if needed
                conditions.append(f'None  # Handle "{db_name}"')

        if (
            len(conditions) == 2
            and "seed" in unique_db_names
            and "current" in unique_db_names
        ):
            new_func += f"""
            return before if name == "seed" else after"""
        else:
            # More complex mapping if needed
            new_func += f"""
            if name == "seed":
                return before
            elif name == "current":
                return after
            else:
                raise ValueError(f"Unknown database name: {{name}}")"""
    else:
        new_func += """
            return before if name == "seed" else after"""

    new_func += """

        @property
        def instance(self):
            return self
        
        def load(self):
            pass

    def verifier(env: Environment, final_answer: Optional[str] = None) -> float:"""

    if docstring:
        new_func += f"\n        {docstring}"

    # First, find the minimum indentation in the body (excluding empty lines)
    body_lines = body.splitlines()
    min_indent = float("inf")
    for line in body_lines:
        if line.strip():  # Non-empty line
            indent_len = len(line) - len(line.lstrip())
            min_indent = min(min_indent, indent_len)

    # If we didn't find any non-empty lines, set min_indent to 0
    if min_indent == float("inf"):
        min_indent = 0

    # Now strip the minimum indentation and re-indent to 8 spaces
    if body_lines:
        indented_lines = []
        for line in body_lines:
            if line.strip():  # Non-empty line
                # Remove the minimum indentation and add 8 spaces
                stripped_line = (
                    line[min_indent:] if len(line) > min_indent else line.lstrip()
                )
                indented_lines.append("        " + stripped_line)
            else:  # Empty line
                indented_lines.append("")

        indented_body = "\n".join(indented_lines)
        new_func += f"\n{indented_body}"

    # Add the return statement
    new_func += "\n\n    return verifier(Environment(), transcript)"

    # Replace TASK_FAILED_SCORE with 0 in the function string
    new_func = new_func.replace("TASK_FAILED_SCORE", "0")

    return new_func


def convert_new_to_old_verifier(verifier_str: str) -> str:
    """
    Convert a verifier function from the new format (before/after: DatabaseSnapshot)
    to the old format (env: Environment).

    This is the inverse of convert_verifier_string.

    Args:
        verifier_str: The new format verifier function as a string

    Returns:
        The converted verifier function string that accepts env
    """
    # Extract function name, parameters, docstring, and body
    # Pattern for new format with flexible whitespace and multiline support
    func_pattern = r'def\s+(\w+)\s*\(\s*before\s*:\s*DatabaseSnapshot\s*,?\s*after\s*:\s*DatabaseSnapshot\s*,?\s*transcript\s*:\s*str\s*\|\s*None\s*=\s*None\s*,?\s*\)\s*->\s*int:\s*((?:\s*""".*?"""\s*)?)(.*)'

    # Try multiline pattern that's more flexible
    func_pattern_multiline = r'def\s+(\w+)\s*\(\s*\n?\s*before\s*:\s*DatabaseSnapshot\s*,?\s*\n?\s*after\s*:\s*DatabaseSnapshot\s*,?\s*\n?\s*transcript\s*:\s*str\s*\|\s*None\s*=\s*None\s*,?\s*\n?\s*\)\s*->\s*int:\s*\n?((?:\s*""".*?"""\s*)?)(.*)'

    match = re.match(
        func_pattern_multiline, verifier_str.strip(), re.DOTALL | re.MULTILINE
    )

    if not match:
        # Even more flexible pattern
        func_pattern_flexible = (
            r'def\s+(\w+)\s*\([^)]*\)\s*->\s*int:\s*\n?((?:\s*""".*?"""\s*)?)(.*)'
        )
        match = re.match(func_pattern_flexible, verifier_str.strip(), re.DOTALL)

        if not match:
            raise ValueError("Could not parse new format verifier function")

    func_name = match.group(1)
    docstring = match.group(2).strip()
    body = match.group(3)

    # Indent the original function body
    indented_verifier = "\n".join(
        "    " + line if line.strip() else line for line in verifier_str.splitlines()
    )

    # Build the wrapper function
    wrapper_func = f'''def {func_name}_wrapper(env, *args, **kwargs) -> float:
    """Wrapper to adapt new format verifier to old format."""
    # Import required modules
    from .verifiers.db import DatabaseSnapshot, IgnoreConfig
    
    # Constants
    TASK_SUCCESSFUL_SCORE = 1
    TASK_FAILED_SCORE = 0
    
    # Extract before and after from env
    before = env.db("seed")
    after = env.db("current")
    
    # Get transcript from kwargs if provided
    transcript = kwargs.get('transcript', kwargs.get('final_answer', None))
    
    # Define the inner function
{indented_verifier}
    
    # Call the inner function and convert result
    result = {func_name}(before, after, transcript)
    return float(result)'''

    return wrapper_func
