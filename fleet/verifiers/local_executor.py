"""Local verifier execution and database diffing against SQLite files.

Executes verifier function code directly against local SQLite database files
and computes structured diffs, without requiring authentication or a remote
runner API server.
"""

import inspect
import json
import re
import string
import traceback
from io import StringIO
from typing import Any, Dict, Optional

from .db import DatabaseSnapshot, IgnoreConfig, SnapshotDiff
from .code import TASK_SUCCESSFUL_SCORE, TASK_FAILED_SCORE


# ---------------------------------------------------------------------------
#  Helper functions injected into verifier execution namespace
# ---------------------------------------------------------------------------

_TRANSLATOR = str.maketrans(string.punctuation, " " * len(string.punctuation))


def _normalize_text(value: str) -> str:
    text = value.lower().translate(_TRANSLATOR)
    return "".join(text.split())


def _stringify_content(content: Any) -> str:
    if isinstance(content, (dict, list)):
        return json.dumps(content, sort_keys=True)
    return str(content)


def normalized_contains(target: str, blob: Any) -> bool:
    """Check if target is contained in blob after normalising punctuation and case."""
    normalized_target = _normalize_text(target)
    normalized_blob = _normalize_text(_stringify_content(blob))
    return normalized_target in normalized_blob


def normalized_string_comparison(target: str, blob: Any) -> bool:
    """Check if target equals blob after normalising punctuation and case."""
    normalized_target = _normalize_text(target)
    normalized_blob = _normalize_text(_stringify_content(blob))
    return normalized_target == normalized_blob


def extract_numbers(text: str) -> list:
    """Extract all numbers from a string."""
    cleaned_text = text.replace(",", "")
    pattern = r"-?\d+\.?\d*"
    matches = re.findall(pattern, cleaned_text)
    return [float(num) for num in matches]


def contains_number(text: str, target_number) -> bool:
    """Check if text contains the target number."""
    numbers = extract_numbers(text)
    try:
        if isinstance(target_number, str):
            target_number = target_number.replace(",", "")
        target = float(target_number)
    except (ValueError, AttributeError):
        return False
    return target in numbers


# ---------------------------------------------------------------------------
#  Lightweight Environment mock for local verifier execution
# ---------------------------------------------------------------------------

class _LocalInstance:
    """Mock instance that supports load() as a no-op."""

    def load(self):
        pass


class LocalEnvironment:
    """Lightweight environment that wraps local SQLite files for verifier execution.

    Provides the same interface verifier functions expect from ``env``:
    ``env.db("seed")``, ``env.db("current")``, and ``env.instance.load()``.
    """

    def __init__(self, seed_db: str, current_db: str):
        self._snapshots: Dict[str, DatabaseSnapshot] = {
            "seed": DatabaseSnapshot(seed_db, name="seed"),
            "current": DatabaseSnapshot(current_db, name="current"),
        }
        self.instance = _LocalInstance()

    def db(self, name: str = "current") -> DatabaseSnapshot:
        if name not in self._snapshots:
            raise KeyError(
                f"Unknown database '{name}'. Available: {list(self._snapshots.keys())}"
            )
        return self._snapshots[name]


# ---------------------------------------------------------------------------
#  Core execution function
# ---------------------------------------------------------------------------

def execute_verifier_local(
    verifier_func: str,
    seed_db: str,
    current_db: str,
    final_answer: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute a verifier function string locally against SQLite database files.

    No authentication or remote server required. The function is executed in an
    isolated namespace with the same helpers available to production verifiers.

    Args:
        verifier_func: Python source code containing the verifier function definition.
        seed_db: Path to the seed (before) SQLite database file.
        current_db: Path to the current (after) SQLite database file.
        final_answer: Optional final answer string passed to the verifier.

    Returns:
        Dict with keys:
            - ``success`` (bool): Whether execution completed without errors.
            - ``result`` (Any): The return value of the verifier function (typically a score).
            - ``error`` (str | None): Error message and traceback if execution failed.
            - ``stdout`` (str): Captured stdout output from the verifier function.
    """
    import sys

    # Capture stdout
    captured_stdout = StringIO()

    try:
        # Build the local environment
        env = LocalEnvironment(seed_db, current_db)

        # Clean the verifier code – strip decorators and fleet imports
        cleaned_code = re.sub(r"@verifier\([^)]*\)\s*\n", "", verifier_func)
        cleaned_code = re.sub(
            r"^from fleet\.verifiers.*import.*$\n?",
            "",
            cleaned_code,
            flags=re.MULTILINE,
        )
        cleaned_code = re.sub(
            r"^from fleet import verifier.*$\n?",
            "",
            cleaned_code,
            flags=re.MULTILINE,
        )
        cleaned_code = re.sub(
            r"^import fleet\.verifiers.*$\n?",
            "",
            cleaned_code,
            flags=re.MULTILINE,
        )
        cleaned_code = re.sub(
            r"^import fleet$\n?", "", cleaned_code, flags=re.MULTILINE
        )

        # Build execution namespace with all helpers available to verifiers
        exec_globals: Dict[str, Any] = {
            # Score constants
            "TASK_SUCCESSFUL_SCORE": TASK_SUCCESSFUL_SCORE,
            "TASK_FAILED_SCORE": TASK_FAILED_SCORE,
            # Helper functions
            "normalized_contains": normalized_contains,
            "normalized_string_comparison": normalized_string_comparison,
            "extract_numbers": extract_numbers,
            "contains_number": contains_number,
            # Database classes
            "DatabaseSnapshot": DatabaseSnapshot,
            "IgnoreConfig": IgnoreConfig,
            "SnapshotDiff": SnapshotDiff,
            # Environment type hint (not enforced at runtime)
            "Environment": type(env),
            # Standard library modules commonly used in verifiers
            "json": json,
            "re": re,
            "string": string,
            # Builtins
            "__builtins__": __builtins__,
        }

        # Execute the verifier code to define the function(s)
        local_namespace: Dict[str, Any] = {}
        exec(cleaned_code, exec_globals, local_namespace)

        # Merge so helper functions defined in verifier code are accessible
        exec_globals.update(local_namespace)

        # Find the verifier function (the one defined in user code)
        func_obj = None
        for name, obj in local_namespace.items():
            if inspect.isfunction(obj) and obj.__code__.co_filename == "<string>":
                func_obj = obj
                break

        if func_obj is None:
            return {
                "success": False,
                "result": None,
                "error": "No function found in verifier code",
                "stdout": "",
            }

        # Redirect stdout to capture print() output from verifiers
        old_stdout = sys.stdout
        sys.stdout = captured_stdout

        try:
            # Execute the verifier – verifiers take (env, final_answer=None)
            sig = inspect.signature(func_obj)
            params = list(sig.parameters.values())

            if len(params) >= 2:
                result = func_obj(env, final_answer)
            elif len(params) == 1:
                result = func_obj(env)
            else:
                result = func_obj()
        finally:
            sys.stdout = old_stdout

        return {
            "success": True,
            "result": result,
            "error": None,
            "stdout": captured_stdout.getvalue(),
        }

    except Exception as e:
        # Restore stdout if it was redirected
        if sys.stdout is not sys.__stdout__ and sys.stdout is captured_stdout:
            sys.stdout = sys.__stdout__

        error_msg = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
        return {
            "success": False,
            "result": None,
            "error": error_msg,
            "stdout": captured_stdout.getvalue(),
        }


# ---------------------------------------------------------------------------
#  Structured database diff (matches /diff/structured response format)
# ---------------------------------------------------------------------------

def diff_dbs(
    seed_db: str,
    current_db: str,
    ignore_tables: Optional[set] = None,
    ignore_table_fields: Optional[dict] = None,
) -> Dict[str, Any]:
    """Compute a structured diff between two SQLite databases locally.

    Returns the exact same format as the runner's ``/diff/structured`` endpoint:

    .. code-block:: python

        {
            "success": True,
            "diff": {
                "table_name": {
                    "table_name": str,
                    "primary_key": [str],
                    "added_rows": [{"row_id": ..., "data": {...}}],
                    "removed_rows": [{"row_id": ..., "data": {...}}],
                    "modified_rows": [{"row_id": ..., "changes": {...}, "data": {...}}],
                    "unchanged_count": int,
                    "total_changes": int,
                }
            },
            "message": str,
        }

    No authentication or network access required.

    Args:
        seed_db: Path to the seed (before) SQLite database file.
        current_db: Path to the current (after) SQLite database file.
        ignore_tables: Optional set of table names to skip entirely.
        ignore_table_fields: Optional mapping of ``{table_name: {field, ...}}``
            whose fields are stripped from the diff output.

    Returns:
        Dict matching the ``StructuredDiffResponse`` schema.
    """
    from .sql_differ import SQLiteDiffer

    ignore_tables = ignore_tables or set()
    ignore_table_fields = ignore_table_fields or {}

    try:
        differ = SQLiteDiffer(seed_db, current_db)
        raw_diff = differ.diff_all_tables()

        filtered_diff: Dict[str, Any] = {}
        for table_name, table_diff in raw_diff.items():
            if table_name in ignore_tables:
                continue

            # Skip tables that errored during diffing
            if "error" in table_diff:
                continue

            ignored_fields = ignore_table_fields.get(table_name, set())

            # Added rows
            filtered_added = []
            for row in table_diff.get("added_rows", []):
                filtered_data = {
                    k: v for k, v in row["data"].items() if k not in ignored_fields
                }
                filtered_added.append({"row_id": row["row_id"], "data": filtered_data})

            # Removed rows
            filtered_removed = []
            for row in table_diff.get("removed_rows", []):
                filtered_data = {
                    k: v for k, v in row["data"].items() if k not in ignored_fields
                }
                filtered_removed.append({"row_id": row["row_id"], "data": filtered_data})

            # Modified rows
            filtered_modified = []
            for row in table_diff.get("modified_rows", []):
                filtered_changes = {
                    k: v for k, v in row["changes"].items() if k not in ignored_fields
                }
                if filtered_changes:
                    after_row = row.get("after_row", {})
                    filtered_data = {
                        k: v for k, v in after_row.items() if k not in ignored_fields
                    }
                    filtered_modified.append({
                        "row_id": row["row_id"],
                        "changes": filtered_changes,
                        "data": filtered_data,
                    })

            total_changes = len(filtered_added) + len(filtered_removed) + len(filtered_modified)

            filtered_diff[table_name] = {
                "table_name": table_name,
                "primary_key": table_diff.get("primary_key", []),
                "added_rows": filtered_added,
                "removed_rows": filtered_removed,
                "modified_rows": filtered_modified,
                "unchanged_count": table_diff.get("unchanged_count", 0),
                "total_changes": total_changes,
            }

        return {
            "success": True,
            "diff": filtered_diff,
            "message": "Structured diff generated successfully",
        }

    except Exception as e:
        return {
            "success": False,
            "diff": {},
            "message": f"Failed to generate structured diff: {e}",
        }
