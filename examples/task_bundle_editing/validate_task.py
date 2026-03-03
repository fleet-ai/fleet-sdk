#!/usr/bin/env python3
"""
Validate a downloaded task bundle before uploading.

Checks:
  1. task.json exists and is valid JSON
  2. Required fields present and non-empty
  3. Verifier code is syntactically valid Python
  4. Verifier uses expected function signature
  5. files/ directory exists (may be empty)
  6. No files exceed size limit
  7. Data files are under files/notebooks/ (agent workspace) and match
     the list_workspace_files() pattern in the prompt
  8. Key format is valid

Usage:
    python validate_task.py ./my_task
    python validate_task.py ./my_task --new-key my_new_key
"""

import argparse
import ast
import glob
import json
import re
import sys
from pathlib import Path

MAX_FILE_SIZE_MB = 50
MAX_TOTAL_SIZE_MB = 200


def validate(bundle_dir: Path, new_key: str | None = None) -> list[str]:
    """Validate a task bundle directory. Returns list of errors (empty = valid)."""
    errors = []
    warnings = []

    # -- 1. task.json existence and parse --
    task_path = bundle_dir / "task.json"
    if not task_path.exists():
        errors.append("task.json not found")
        return errors

    try:
        task = json.loads(task_path.read_text())
    except json.JSONDecodeError as e:
        errors.append(f"task.json is not valid JSON: {e}")
        return errors

    # -- 2. Required fields --
    required_fields = {
        "key": str,
        "prompt": str,
        "environment_id": str,
    }
    for field, expected_type in required_fields.items():
        val = task.get(field)
        if val is None:
            errors.append(f"Missing required field: {field}")
        elif not isinstance(val, expected_type):
            errors.append(
                f"Field '{field}' should be {expected_type.__name__}, "
                f"got {type(val).__name__}"
            )
        elif isinstance(val, str) and not val.strip():
            errors.append(f"Field '{field}' is empty")

    # Check prompt length
    prompt = task.get("prompt", "")
    if isinstance(prompt, str):
        if len(prompt) < 20:
            errors.append(f"Prompt suspiciously short ({len(prompt)} chars)")
        elif len(prompt) > 50000:
            warnings.append(f"Prompt very long ({len(prompt)} chars)")

    # Optional but expected fields
    if not task.get("version"):
        warnings.append("No 'version' specified (will use latest)")

    # -- 3. env_variables --
    env_vars = task.get("env_variables")
    if env_vars:
        task_key_var = env_vars.get("TASK_KEY")
        if task_key_var and new_key and task_key_var != new_key:
            warnings.append(
                f"env_variables.TASK_KEY='{task_key_var}' doesn't match "
                f"new key '{new_key}' (upload_task will override this)"
            )

    # -- 4. Verifier code --
    verifier = task.get("verifier")
    if verifier:
        code = verifier.get("code")
        if not code:
            warnings.append("Verifier present but has no code")
        else:
            # Check syntax
            try:
                tree = ast.parse(code)
            except SyntaxError as e:
                errors.append(f"Verifier code has syntax error: {e}")
                tree = None

            if tree:
                # Check for expected function
                func_names = [
                    node.name
                    for node in ast.walk(tree)
                    if isinstance(node, ast.FunctionDef)
                ]
                valid_names = {"verify", "verifier", "grade"}
                if not any(name in valid_names for name in func_names):
                    warnings.append(
                        f"Verifier defines functions {func_names}, "
                        f"expected one of {valid_names}"
                    )

                # Check function signature has 'env' param
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef) and node.name in valid_names:
                        arg_names = [a.arg for a in node.args.args]
                        if "env" not in arg_names:
                            errors.append(
                                f"Verifier function '{node.name}' missing 'env' parameter"
                            )

            # -- 4b. Verify S3 solution paths reference the correct task key --
            # Verifiers often load gold-reference images via Image.s3() with
            # URLs like .../&lt;TASK_KEY&gt;/solutions/gold_plot.png.  The TASK_KEY
            # env variable must appear as a path segment in every such URL,
            # otherwise the verifier will silently load the wrong solutions.
            if code:
                expected_key = (
                    new_key
                    or (task.get("env_variables") or {}).get("TASK_KEY")
                    or task.get("key", "")
                )
                s3_urls = re.findall(
                    r'https?://[^"\']+\.s3[^"\']*\.amazonaws\.com/[^"\'\s]+',
                    code,
                )
                solutions_urls = [u for u in s3_urls if "/solutions/" in u]
                for url in solutions_urls:
                    path_segments = url.split("/")
                    if expected_key not in path_segments:
                        errors.append(
                            f"Verifier S3 solutions path does not contain "
                            f"expected key '{expected_key}' as a path segment: "
                            f"{url}"
                        )
    else:
        warnings.append("No verifier in task.json")

    # -- 5. Files directory --
    files_dir = bundle_dir / "files"
    if not files_dir.exists():
        warnings.append("No 'files/' directory (task has no data files)")
        all_files = []
    else:
        all_files = [p for p in files_dir.rglob("*") if p.is_file()]
        if not all_files:
            warnings.append("files/ directory exists but is empty")

    # -- 6. File sizes --
    total_size = 0
    for f in all_files:
        size = f.stat().st_size
        total_size += size
        size_mb = size / (1024 * 1024)
        if size_mb > MAX_FILE_SIZE_MB:
            errors.append(
                f"File too large ({size_mb:.1f} MB): {f.relative_to(bundle_dir)}"
            )

    total_mb = total_size / (1024 * 1024)
    if total_mb > MAX_TOTAL_SIZE_MB:
        errors.append(
            f"Total file size {total_mb:.1f} MB exceeds {MAX_TOTAL_SIZE_MB} MB limit"
        )

    # -- 7. Data file location checks --
    # In Carlisle, files under files/notebooks/ are unpacked to /app/workspace/
    # at startup. The prompt tells agents to use list_workspace_files(pattern=...)
    # to find data. Warn if the prompt references a path that doesn't match
    # any files, or if data files are placed outside the notebooks/ tree.
    if all_files:
        notebooks_dir = files_dir / "notebooks"

        # Check that data files live under files/notebooks/ (the only path
        # that gets unpacked into the agent workspace)
        files_outside_notebooks = [
            f for f in all_files
            if not str(f.relative_to(files_dir)).startswith("notebooks/")
            and not str(f.relative_to(files_dir)).startswith("solutions/")
        ]
        if files_outside_notebooks:
            warnings.append(
                f"{len(files_outside_notebooks)} file(s) outside notebooks/ and "
                f"solutions/ — these won't be visible in the agent workspace. "
                f"e.g. {files_outside_notebooks[0].relative_to(files_dir)}"
            )

        # Extract list_workspace_files(pattern="...") from the prompt and
        # verify matching files exist under files/notebooks/
        workspace_patterns = re.findall(
            r'list_workspace_files\(pattern=["\']([^"\']+)["\']\)', prompt
        )
        for wp in workspace_patterns:
            # The agent sees /app/workspace/{wp}, which maps to
            # files/notebooks/{wp} in the bundle
            expected_glob = str(notebooks_dir / wp)
            matches = glob.glob(expected_glob, recursive=True)
            matches = [m for m in matches if Path(m).is_file()]
            if not matches:
                errors.append(
                    f"Prompt references list_workspace_files(pattern=\"{wp}\") "
                    f"but no files match files/notebooks/{wp}"
                )
            else:
                # Informational — not a warning, just context for the report
                pass

        if not workspace_patterns and notebooks_dir.exists():
            warnings.append(
                "Prompt has no list_workspace_files() call — agent may not "
                "know how to find the data files"
            )

    # -- 8. Key format --
    key = new_key or task.get("key", "")
    if key:
        if " " in key:
            errors.append(f"Key contains spaces: '{key}'")
        if len(key) > 200:
            errors.append(f"Key too long ({len(key)} chars, max 200)")

    # -- Print results --
    print(f"\n{'=' * 60}")
    print(f"  Task Bundle Validation: {bundle_dir.name}")
    print(f"{'=' * 60}")
    print(f"  Key:            {task.get('key', 'N/A')}")
    if new_key:
        print(f"  New key:        {new_key}")
    print(f"  Environment:    {task.get('environment_id', 'N/A')}")
    print(f"  Version:        {task.get('version', 'N/A')}")
    print(f"  Prompt:         {len(task.get('prompt', ''))} chars")
    print(f"  Verifier:       {'yes' if verifier and verifier.get('code') else 'no'}")
    print(f"  Files:          {len(all_files)} ({total_mb:.2f} MB total)")
    if all_files:
        for f in all_files:
            rel = f.relative_to(files_dir)
            size_kb = f.stat().st_size / 1024
            print(f"    - {rel} ({size_kb:.0f} KB)")

    if warnings:
        print(f"\n  Warnings ({len(warnings)}):")
        for w in warnings:
            print(f"    [!] {w}")

    if errors:
        print(f"\n  ERRORS ({len(errors)}):")
        for e in errors:
            print(f"    [X] {e}")
        print(f"\n  RESULT: FAIL")
    else:
        print(f"\n  RESULT: PASS")

    print(f"{'=' * 60}\n")
    return errors


def main():
    parser = argparse.ArgumentParser(
        description="Validate a task bundle before upload"
    )
    parser.add_argument("bundle_dir", help="Path to the task bundle directory")
    parser.add_argument(
        "--new-key", help="New key to use (checks consistency)"
    )
    args = parser.parse_args()

    bundle_dir = Path(args.bundle_dir)
    if not bundle_dir.is_dir():
        print(f"Error: {bundle_dir} is not a directory")
        sys.exit(1)

    errors = validate(bundle_dir, new_key=args.new_key)
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
