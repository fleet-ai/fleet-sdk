"""Verifier code parsing and validation utilities."""

import ast
from typing import Set


def parse_and_validate_verifier(code: str) -> str:
    """Parse and validate verifier code, returning the first function name.

    This function ensures that the verifier code only contains safe declarative
    statements and does not execute arbitrary code during import.

    Args:
        code: Python code string containing the verifier function

    Returns:
        Name of the first function found in the code

    Raises:
        ValueError: If code is invalid or contains unsafe statements
        SyntaxError: If code has syntax errors
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise SyntaxError(f"Syntax error in verifier code: {e}")

    first_function_name = None

    for node in tree.body:
        # Check for function definitions
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Validate that decorators don't contain function calls
            for decorator in node.decorator_list:
                if _contains_call(decorator):
                    raise ValueError(
                        f"Line {node.lineno}: Function decorators with function calls "
                        f"are not allowed. Decorators execute during import and could "
                        f"run arbitrary code."
                    )

            if first_function_name is None:
                first_function_name = node.name
            continue

        # Allow imports
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            continue

        # Allow class definitions
        if isinstance(node, ast.ClassDef):
            continue

        # Allow docstrings and other expression statements (but not calls)
        if isinstance(node, ast.Expr):
            if isinstance(node.value, ast.Constant):
                # Docstring or constant expression - safe
                continue
            else:
                # Check if it's a call or other dangerous expression
                raise ValueError(
                    f"Line {node.lineno}: Expression statements that are not "
                    f"constants are not allowed at module level. Found: {ast.dump(node.value)}"
                )

        # Allow variable assignments, but check the value
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            # Check if the assignment value contains any function calls
            if _contains_call(node.value if isinstance(node, ast.AnnAssign) else node.value):
                raise ValueError(
                    f"Line {node.lineno}: Variable assignments with function calls "
                    f"are not allowed at module level. This prevents arbitrary code "
                    f"execution during import."
                )
            continue

        # If we get here, it's an unsupported statement type
        raise ValueError(
            f"Line {node.lineno}: Unsupported statement type at module level: "
            f"{node.__class__.__name__}. Only imports, function/class definitions, "
            f"and constant assignments are allowed."
        )

    if first_function_name is None:
        raise ValueError("No function found in verifier code")

    return first_function_name


def _contains_call(node: ast.AST) -> bool:
    """Recursively check if an AST node contains any Call nodes.

    Args:
        node: AST node to check

    Returns:
        True if the node or any of its children is a Call node
    """
    if isinstance(node, ast.Call):
        return True

    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            return True

    return False
