import argparse
import json
import re
import sys
from typing import Dict, Tuple, Optional


def extract_function_info(function_code: str) -> Optional[Tuple[str, bool]]:
    """
    Extract function name and async status from Python function code.
    Handles both regular functions (def) and async functions (async def).

    Args:
        function_code: Python function code as a string

    Returns:
        A tuple of (function_name, is_async) if found, None otherwise
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
    pattern = r"^\s*(?:@[\w\.\n+() ,]*\n\s*)*(async\s+)?def\s+([A-Za-z_]\w*)\s*\("

    match = re.search(pattern, code, flags=re.MULTILINE)
    if match:
        is_async = match.group(1) is not None
        function_name = match.group(2)
        return (function_name, is_async)

    # Fallback: search anywhere (not anchored) for a def signature
    fallback = r"(async\s+)?def\s+([A-Za-z_]\w*)\s*\("
    match = re.search(fallback, code)
    if match:
        is_async = match.group(1) is not None
        function_name = match.group(2)
        return (function_name, is_async)

    return None


def clean_verifier_code(code: str) -> str:
    """
    Clean verifier code by removing markdown code fences and normalizing whitespace.

    Args:
        code: Raw verifier code string

    Returns:
        Cleaned code string
    """
    # Normalize escaped newlines
    code = code.replace("\\n", "\n").strip()

    # Remove markdown code fences if present
    if "```" in code:
        fence_blocks = re.findall(r"```[a-zA-Z0-9_+-]*\n([\s\S]*?)\n```", code)
        if fence_blocks:
            code = fence_blocks[0].strip()

    return code


def extract_verifiers_to_file(json_path: str, py_path: str) -> None:
    """
    Extract verifiers from JSON file and write them to a Python file with decorators.

    Args:
        json_path: Path to input JSON file
        py_path: Path to output Python file
    """
    print(f"Reading tasks from: {json_path}")

    # Load JSON file
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            tasks = json.load(f)
    except FileNotFoundError:
        print(f"✗ Error: File '{json_path}' not found")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"✗ Error: Invalid JSON in '{json_path}': {e}")
        sys.exit(1)

    if not isinstance(tasks, list):
        print("✗ Error: JSON file must contain an array of tasks")
        sys.exit(1)

    print(f"Found {len(tasks)} task(s)")

    # Extract verifiers
    verifiers = []
    missing_verifier = []
    duplicate_keys = set()
    seen_keys = set()

    for i, task in enumerate(tasks):
        task_key = task.get("key") or task.get("id")
        if not task_key:
            print(f"⚠ Warning: Task at index {i} has no key or id, skipping")
            continue

        # Check for duplicate keys
        if task_key in seen_keys:
            duplicate_keys.add(task_key)
            print(f"⚠ Warning: Duplicate task key '{task_key}' found")
        seen_keys.add(task_key)

        # Get verifier code from multiple possible locations
        verifier_code = (
            task.get("verifier_func")
            or task.get("verifier_code")
            or task.get("metadata", {}).get("verifier_code")
        )

        if not verifier_code:
            missing_verifier.append(task_key)
            continue

        # Clean the code
        cleaned_code = clean_verifier_code(verifier_code)

        # Extract function info
        func_info = extract_function_info(cleaned_code)
        if not func_info:
            print(
                f"⚠ Warning: Could not extract function name from verifier for task '{task_key}'"
            )
            continue

        function_name, is_async = func_info

        verifiers.append(
            {
                "task_key": task_key,
                "function_name": function_name,
                "is_async": is_async,
                "code": cleaned_code,
            }
        )

    if missing_verifier:
        print(f"\n⚠ Warning: {len(missing_verifier)} task(s) missing verifier code:")
        for key in missing_verifier[:10]:  # Show first 10
            print(f"  - {key}")
        if len(missing_verifier) > 10:
            print(f"  ... and {len(missing_verifier) - 10} more")

    if duplicate_keys:
        print(f"\n⚠ Warning: {len(duplicate_keys)} duplicate task key(s) found:")
        for key in list(duplicate_keys)[:10]:
            print(f"  - {key}")

    print(f"\n✓ Extracted {len(verifiers)} verifier(s)")

    # Count async vs sync
    async_count = sum(1 for v in verifiers if v["is_async"])
    sync_count = len(verifiers) - async_count
    print(f"  - {async_count} async verifier(s)")
    print(f"  - {sync_count} sync verifier(s)")

    # Write to Python file
    print(f"\nWriting verifiers to: {py_path}")

    with open(py_path, "w", encoding="utf-8") as f:
        # Write header
        f.write('"""Auto-generated verifiers file.\n\n')
        f.write(f"Extracted from: {json_path}\n")
        f.write(f"Total verifiers: {len(verifiers)}\n")
        f.write(f"  - Async: {async_count}\n")
        f.write(f"  - Sync: {sync_count}\n")
        f.write('"""\n\n')

        # Write imports
        f.write("# Import verifier decorators and dependencies\n")
        f.write("from fleet import (\n")
        f.write("    verifier,\n")
        f.write("    AsyncEnv,\n")
        f.write("    SyncEnv,\n")
        f.write("    SyncEnv as Environment,\n")
        f.write("    AsyncEnv as AsyncEnvironment,\n")
        f.write("    IgnoreConfig,\n")
        f.write("    TASK_FAILED_SCORE,\n")
        f.write("    TASK_SUCCESSFUL_SCORE,\n")
        f.write(")\n")
        f.write("from fleet.verifiers.verifier import verifier as verifier_sync\n")
        f.write("\n")
        f.write("# Standard library imports used in verifiers\n")
        f.write("import json\n")
        f.write("import re\n")
        f.write("import string\n")
        f.write("from typing import Any\n")
        f.write("\n")
        f.write("# Helper functions available in verifier namespace\n")
        f.write(
            '_TRANSLATOR = str.maketrans(string.punctuation, " " * len(string.punctuation))\n'
        )
        f.write("\n")
        f.write("def _normalize_text(value: str) -> str:\n")
        f.write("    text = value.lower().translate(_TRANSLATOR)\n")
        f.write('    return "".join(text.split())\n')
        f.write("\n")
        f.write("def _stringify_content(content: Any) -> str:\n")
        f.write("    if isinstance(content, (dict, list)):\n")
        f.write("        return json.dumps(content, sort_keys=True)\n")
        f.write("    return str(content)\n")
        f.write("\n")
        f.write("def normalized_contains(target: str, blob: Any) -> bool:\n")
        f.write("    normalized_target = _normalize_text(target)\n")
        f.write("    normalized_blob = _normalize_text(_stringify_content(blob))\n")
        f.write("    return normalized_target in normalized_blob\n")
        f.write("\n")
        f.write("def extract_numbers(text: str) -> list:\n")
        f.write("    cleaned_text = text.replace(',', '')\n")
        f.write("    pattern = r'-?\\d+\\.?\\d*'\n")
        f.write("    matches = re.findall(pattern, cleaned_text)\n")
        f.write("    return [float(num) for num in matches]\n")
        f.write("\n")
        f.write("def contains_number(text: str, target_number) -> bool:\n")
        f.write("    numbers = extract_numbers(text)\n")
        f.write("    try:\n")
        f.write("        if isinstance(target_number, str):\n")
        f.write("            target_number = target_number.replace(',', '')\n")
        f.write("        target = float(target_number)\n")
        f.write("    except (ValueError, AttributeError):\n")
        f.write("        return False\n")
        f.write("    return target in numbers\n")
        f.write("\n")
        f.write("# " + "=" * 78 + "\n")
        f.write("# VERIFIERS\n")
        f.write("# " + "=" * 78 + "\n\n")

        # Write each verifier
        for i, ver in enumerate(verifiers):
            # Write separator comment
            if i > 0:
                f.write("\n" + "# " + "-" * 78 + "\n\n")

            # Write task key comment
            f.write(f"# Task: {ver['task_key']}\n")
            f.write(
                f"# Function: {ver['function_name']} ({'async' if ver['is_async'] else 'sync'})\n"
            )

            # Write decorator - use verifier for async, verifier_sync for sync
            decorator_name = "verifier" if ver["is_async"] else "verifier_sync"
            f.write(f'@{decorator_name}(key="{ver["task_key"]}")\n')

            # Write function code
            f.write(ver["code"])
            f.write("\n")

    print(f"✓ Successfully wrote {len(verifiers)} verifier(s) to '{py_path}'")
    print("\nNext steps:")
    print(f"  1. Edit the verifiers in '{py_path}'")
    print(f"  2. Run: python {sys.argv[0]} apply {json_path} {py_path}")


def parse_verifiers_from_file(python_path: str) -> Dict[str, str]:
    """
    Parse verifiers from a Python file and extract them by task key.

    Args:
        python_path: Path to Python file containing verifiers

    Returns:
        Dictionary mapping task_key to verifier code
    """
    print(f"Reading verifiers from: {python_path}")

    try:
        with open(python_path, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        print(f"✗ Error: File '{python_path}' not found")
        sys.exit(1)

    # Split content by the separator comments to get individual verifier sections
    # The separator is "# ------------------------------------------------------------------------------"
    # Each section starts with "# Task: <key>"

    verifiers = {}

    # Split by "# Task: " markers to find each verifier block
    task_blocks = re.split(r"\n# Task: ", content)

    for block in task_blocks[1:]:  # Skip the first block (header)
        # Extract task key from the first line
        lines = block.split("\n")
        if not lines:
            continue

        # First line should be the task key
        task_key = lines[0].strip()

        # Find the @verifier or @verifier_sync decorator to extract the key parameter
        verifier_match = re.search(
            r'@verifier(?:_sync)?\(key=["\']([^"\']+)["\']\s*(?:,\s*[^)]+)?\)', block
        )
        if verifier_match:
            task_key = verifier_match.group(1)

        # Find the function definition (async def or def)
        # Extract from the function start until we hit the separator or end
        func_pattern = r"((async\s+)?def\s+\w+.*?)(?=\n# -+\n|\n# Task:|\Z)"
        func_match = re.search(func_pattern, block, re.DOTALL)

        if func_match:
            function_code = func_match.group(1).strip()
            verifiers[task_key] = function_code

    # If the above approach didn't work, try a direct pattern match
    if not verifiers:
        # Pattern to match @verifier or @verifier_sync decorator with key and the following function
        # Look for the decorator, then capture everything until we hit a dedented line or separator
        pattern = r'@verifier(?:_sync)?\(key=["\']([^"\']+)["\']\s*(?:,\s*[^)]+)?\)\s*\n((?:async\s+)?def\s+[^\n]+:(?:\n(?:    |\t).*)*(?:\n(?:    |\t).*)*)'

        matches = re.findall(pattern, content, re.MULTILINE)

        for task_key, function_code in matches:
            verifiers[task_key] = function_code.strip()

    print(f"✓ Found {len(verifiers)} verifier(s)")

    # Analyze async vs sync
    async_count = 0
    sync_count = 0
    for code in verifiers.values():
        func_info = extract_function_info(code)
        if func_info:
            _, is_async = func_info
            if is_async:
                async_count += 1
            else:
                sync_count += 1

    print(f"  - {async_count} async verifier(s)")
    print(f"  - {sync_count} sync verifier(s)")

    return verifiers


def apply_verifiers_to_json(json_path: str, python_path: str) -> None:
    """
    Apply verifiers from Python file back into JSON task file (updates in-place).

    Args:
        json_path: Path to JSON file to update
        python_path: Path to Python file with verifiers
    """
    # Parse verifiers from Python file
    verifiers = parse_verifiers_from_file(python_path)

    # Load JSON file
    print(f"\nReading tasks from: {json_path}")
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            tasks = json.load(f)
    except FileNotFoundError:
        print(f"✗ Error: File '{json_path}' not found")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"✗ Error: Invalid JSON in '{json_path}': {e}")
        sys.exit(1)

    if not isinstance(tasks, list):
        print("✗ Error: JSON file must contain an array of tasks")
        sys.exit(1)

    print(f"Found {len(tasks)} task(s)")

    # Update tasks with new verifiers (only if changed)
    updated_count = 0
    not_found = []

    for task in tasks:
        task_key = task.get("key") or task.get("id")
        if not task_key:
            continue

        if task_key in verifiers:
            new_code = verifiers[task_key]
            old_code = task.get("verifier_func", "").strip()

            # Only update if the code actually changed
            if old_code != new_code.strip():
                # Update verifier_func with new code
                task["verifier_func"] = new_code

                # Also update metadata if it exists
                if "metadata" in task and isinstance(task["metadata"], dict):
                    task["metadata"]["verifier_code"] = new_code
                    # Increment version if it exists
                    if "verifier_version" in task["metadata"]:
                        task["metadata"]["verifier_version"] += 1

                # Clear verifier_id and verifier_sha to force re-upload
                task["verifier_id"] = None
                task["verifier_sha"] = None

                updated_count += 1
        else:
            not_found.append(task_key)

    print(f"\n✓ Updated {updated_count} task(s) with new verifiers")

    if not_found:
        print(f"\n⚠ Warning: {len(not_found)} task(s) not found in Python file:")
        for key in not_found[:10]:
            print(f"  - {key}")
        if len(not_found) > 10:
            print(f"  ... and {len(not_found) - 10} more")

    # Write output back to the same JSON file
    print(f"\nWriting updated tasks to: {json_path}")

    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(tasks, f, indent=2, ensure_ascii=False)
        print(f"✓ Successfully updated {len(tasks)} task(s) in '{json_path}'")
    except Exception as e:
        print(f"✗ Error writing JSON file: {e}")
        sys.exit(1)


def validate_verifiers_file(python_path: str) -> None:
    """
    Validate that a Python verifiers file can be parsed correctly.

    Args:
        python_path: Path to Python file with verifiers
    """
    verifiers = parse_verifiers_from_file(python_path)

    print("\nValidating verifiers...")
    errors = []

    for task_key, code in verifiers.items():
        func_info = extract_function_info(code)
        if not func_info:
            errors.append(f"  - {task_key}: Could not extract function info")
        else:
            function_name, is_async = func_info
            print(
                f"  ✓ {task_key}: {function_name} ({'async' if is_async else 'sync'})"
            )

    if errors:
        print(f"\n✗ Found {len(errors)} error(s):")
        for error in errors:
            print(error)
        sys.exit(1)
    else:
        print(f"\n✓ All {len(verifiers)} verifier(s) are valid!")


def main():
    parser = argparse.ArgumentParser(
        description="Iterate on verifier code from JSON task files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Extract verifiers from JSON to Python file
  %(prog)s extract xai-day-10-batch.json verifiers.py
  
  # Edit verifiers.py...
  
  # Apply changes back to JSON file (updates in-place)
  %(prog)s apply xai-day-10-batch.json verifiers.py
  
  # Validate verifiers file
  %(prog)s validate verifiers.py
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")
    subparsers.required = True

    # Extract command
    extract_parser = subparsers.add_parser(
        "extract", help="Extract verifiers from JSON to Python file"
    )
    extract_parser.add_argument("json_file", help="Path to JSON file containing tasks")
    extract_parser.add_argument("py_file", help="Path to output Python file")

    # Apply command
    apply_parser = subparsers.add_parser(
        "apply", help="Apply verifiers from Python file back to JSON (updates in-place)"
    )
    apply_parser.add_argument("json_file", help="Path to JSON file to update")
    apply_parser.add_argument("py_file", help="Path to Python file with verifiers")

    # Validate command
    validate_parser = subparsers.add_parser("validate", help="Validate verifiers file")
    validate_parser.add_argument("py_file", help="Path to Python file with verifiers")

    args = parser.parse_args()

    # Execute command
    if args.command == "extract":
        extract_verifiers_to_file(args.json_file, args.py_file)
    elif args.command == "apply":
        apply_verifiers_to_json(args.json_file, args.py_file)
    elif args.command == "validate":
        validate_verifiers_file(args.py_file)


if __name__ == "__main__":
    main()
