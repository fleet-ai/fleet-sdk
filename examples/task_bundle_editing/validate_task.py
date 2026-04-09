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
  7. Data files are under files/notebooks/ (agent workspace)
  8. Key format is valid

Usage:
    python validate_task.py ./my_task
    python validate_task.py ./my_task --new-key my_new_key
"""

import argparse
import ast
import json
import re
import sys
from pathlib import Path

MAX_FILE_SIZE_MB = 2000
MAX_TOTAL_SIZE_MB = 5000


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
            if tree and code:
                # Check that verifier reads agent output files via File.from_env
                # rather than env.read_file() or passing files={}
                uses_file_from_env = "File.from_env" in code
                uses_read_file = "env.read_file" in code or "read_file(" in code
                passes_empty_files = "files={}" in code

                if uses_read_file:
                    warnings.append(
                        "Verifier uses env.read_file() which is undocumented and "
                        "unreliable. Use File.from_env(env, filename) instead — "
                        "see verifier_file_access_guide.md"
                    )

                # Check if prompt requests output files that the verifier
                # should be reading
                output_file_patterns = re.findall(
                    r"['\"]([a-zA-Z_]+\.(?:txt|json|csv|py|png|jpg))['\"]",
                    prompt,
                )
                # Filter to likely agent outputs (mentioned in output/save context)
                save_indicators = [
                    "save", "write", "output", "findings", "investigation",
                    "results", "report", "/artifacts/",
                ]
                prompt_lower = prompt.lower()
                likely_outputs = [
                    f for f in set(output_file_patterns)
                    if any(ind in prompt_lower for ind in save_indicators)
                    and f not in ("task.json",)
                ]

                if likely_outputs and not uses_file_from_env:
                    warnings.append(
                        f"Prompt asks agent to produce files "
                        f"({', '.join(sorted(likely_outputs)[:5])}) but verifier "
                        f"does not use File.from_env() to read them. The judge "
                        f"may not see the agent's work. Pass files via the "
                        f"'files' parameter to env.judge.grade()."
                    )

                if passes_empty_files and likely_outputs:
                    warnings.append(
                        "Verifier passes files={} (empty) to env.judge.grade() "
                        "but the prompt requests agent output files. The judge "
                        "will only see the final_answer, not the saved files."
                    )

                # -- 4b. Import module check --
                # fleet.judge is the correct module; fleet.verifier does not exist
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom) and node.module:
                        if node.module == "fleet.verifier":
                            errors.append(
                                "Verifier imports from 'fleet.verifier' which does "
                                "not exist. Use 'from fleet.judge import Rubric, "
                                "Criterion' instead."
                            )

                # -- 4c. Function signature check --
                # Correct: verify(env, final_answer=None, conversation=None)
                # Wrong:   verify(env, submission_dir, solutions_dir=None)
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef) and node.name in valid_names:
                        arg_names = [a.arg for a in node.args.args]
                        if "submission_dir" in arg_names:
                            errors.append(
                                f"Verifier function '{node.name}' uses old signature "
                                f"with 'submission_dir'. Expected: "
                                f"verify(env, final_answer=None, conversation=None)"
                            )
                        if "solutions_dir" in arg_names:
                            warnings.append(
                                f"Verifier function '{node.name}' has 'solutions_dir' "
                                f"parameter. Solutions are accessed via File.s3(), not "
                                f"filesystem paths."
                            )

                # -- 4d. Criterion API check --
                # Correct: Criterion("name", max=N, levels={...})
                # Wrong:   Criterion(name=..., weight=..., description=...)
                if "weight=" in code and "Criterion(" in code:
                    errors.append(
                        "Verifier uses Criterion(weight=...) which is not the "
                        "fleet.judge API. Use Criterion(name, max=N, levels={...}) "
                        "instead."
                    )

                # -- 4e. env.judge.grade() call exists --
                if "env.judge.grade(" not in code:
                    warnings.append(
                        "Verifier does not call env.judge.grade(). For LLM-as-judge "
                        "tasks, the verifier should return env.judge.grade(rubric=..., "
                        "submission=..., ...)."
                    )

                # -- 4f. Solutions files vs File.s3 / Image.s3 --
                # If bundle has files/solutions/, verifier should reference them
                solutions_dir = bundle_dir / "files" / "solutions"
                has_solutions = (
                    solutions_dir.exists()
                    and any(
                        f.is_file() and f.name != ".DS_Store"
                        for f in solutions_dir.rglob("*")
                    )
                )
                uses_s3 = ".s3(" in code
                if has_solutions and not uses_s3:
                    warnings.append(
                        "Bundle has files in solutions/ but verifier does not use "
                        "File.s3() or Image.s3() to reference them. The judge may "
                        "not see the gold reference materials."
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
    # at startup. Warn if data files are placed outside the notebooks/ tree.
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
