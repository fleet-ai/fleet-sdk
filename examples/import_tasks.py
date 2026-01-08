import asyncio
import argparse
import json
import os
import sys
import tempfile
from collections import defaultdict
from typing import Dict, List, Tuple
import fleet
from fleet._async.tasks import Task
from dotenv import load_dotenv

load_dotenv()


async def run_verifier_sanity_check(
    tasks: List[Task],
    client: fleet.AsyncFleet,
) -> Tuple[bool, Dict[str, str]]:
    """
    Run sanity check by spinning up instances and running verifiers.

    Args:
        tasks: List of Task objects to verify
        client: AsyncFleet client instance

    Returns:
        Tuple of (all_passed, error_dict) where error_dict maps task_key to error message
    """
    print("\n" + "=" * 60)
    print("Running verifier sanity check...")
    print("=" * 60)

    # Group tasks by env_key×env_version×data_key×data_version
    instance_groups = defaultdict(list)
    for task in tasks:
        # Build the instance key
        env_key = task.env_id or ""
        env_version = task.version or ""
        data_key = task.data_id or ""
        data_version = task.data_version or ""

        instance_key = f"{env_key}×{env_version}×{data_key}×{data_version}"
        instance_groups[instance_key].append(task)

    print(f"\nFound {len(instance_groups)} unique environment/data combinations:")
    for instance_key, group_tasks in instance_groups.items():
        print(f"  {instance_key}: {len(group_tasks)} task(s)")

    # Create all instances in parallel
    print(f"\nCreating {len(instance_groups)} instance(s) in parallel...")
    instance_map = {}

    async def create_instance(instance_key: str) -> Tuple[str, object]:
        """Create a single instance."""
        try:
            env_key, env_version, data_key, data_version = instance_key.split("×")

            # Build env_key_str and data_key_str
            if env_version:
                env_key_str = f"{env_key}:{env_version}"
            else:
                env_key_str = env_key

            if data_key and data_version:
                data_key_str = f"{data_key}:{data_version}"
            elif data_key:
                data_key_str = data_key
            else:
                data_key_str = None

            print(
                f"  Creating instance: {env_key_str}"
                + (f" with data {data_key_str}" if data_key_str else "")
            )
            env = await client.make(env_key=env_key_str, data_key=data_key_str)
            return instance_key, env
        except Exception as e:
            print(f"  ✗ Failed to create instance for {instance_key}: {e}")
            return instance_key, None

    # Create instances concurrently
    instance_results = await asyncio.gather(
        *[create_instance(key) for key in instance_groups.keys()],
        return_exceptions=True,
    )

    for result in instance_results:
        if isinstance(result, Exception):
            print(f"  ✗ Exception creating instance: {result}")
            return False, {"__instance_creation__": str(result)}
        instance_key, env = result
        if env is None:
            return False, {instance_key: "Failed to create instance"}
        instance_map[instance_key] = env

    print(f"✓ Created {len(instance_map)} instance(s)")

    # Run all verifiers in parallel with concurrency limit
    max_concurrent_verifiers = 5  # Limit concurrent verifier executions
    print(
        f"\nRunning {len(tasks)} verifier(s) in parallel (max {max_concurrent_verifiers} concurrent)..."
    )
    errors = {}
    semaphore = asyncio.Semaphore(max_concurrent_verifiers)

    async def run_single_verifier(task, instance_key: str) -> Tuple[str, bool, str]:
        """Run a single verifier and return (task_key, success, error_message)."""
        async with semaphore:
            try:
                env = instance_map[instance_key]
                task_key = task.key

                # Run the verifier
                if task.verifier is None:
                    return task_key, False, "No verifier found"

                result = await task.verify_async(env)

                # For sanity check: we expect verifiers to return 0.0 (TASK_FAILED_SCORE)
                # since we're running on fresh instances with no task completion.
                # This confirms the verifier runs without errors.
                if isinstance(result, float):
                    if result == 0.0:
                        print(f"  ✓ {task_key}: {result:.2f} (correctly returns 0.0)")
                        return task_key, True, ""
                    else:
                        print(
                            f"  ⚠ {task_key}: {result:.2f} (expected 0.0 on fresh instance)"
                        )
                        return (
                            task_key,
                            False,
                            f"Expected 0.0 but got {result:.2f} on fresh instance",
                        )
                else:
                    # Non-float result - verifier ran but didn't return expected type
                    print(f"  ⚠ {task_key}: {result} (expected float 0.0)")
                    return (
                        task_key,
                        False,
                        f"Expected float 0.0 but got {type(result).__name__}: {result}",
                    )

            except Exception as e:
                task_key = task.key
                error_msg = f"{type(e).__name__}: {str(e)}"
                print(f"  ✗ {task_key}: {error_msg}")
                return task_key, False, error_msg

    # Run verifiers concurrently with semaphore
    verifier_results = await asyncio.gather(
        *[
            run_single_verifier(task, instance_key)
            for instance_key, group_tasks in instance_groups.items()
            for task in group_tasks
        ],
        return_exceptions=True,
    )

    # Process results
    for result in verifier_results:
        if isinstance(result, Exception):
            print(f"  ✗ Exception running verifier: {result}")
            errors["__verifier_exception__"] = str(result)
        else:
            task_key, success, error_msg = result
            if not success:
                errors[task_key] = error_msg

    # Clean up instances
    print(f"\nCleaning up {len(instance_map)} instance(s)...")
    cleanup_tasks = [env.close() for env in instance_map.values()]
    await asyncio.gather(*cleanup_tasks, return_exceptions=True)
    print("✓ Cleanup complete")

    # Summary
    passed_count = len(tasks) - len(errors)
    print("\n" + "=" * 60)
    print(f"Sanity check complete: {passed_count}/{len(tasks)} passed")

    if errors:
        print(f"\n✗ {len(errors)} verifier(s) failed:")
        for task_key, error_msg in list(errors.items())[:10]:
            print(f"  - {task_key}: {error_msg}")
        if len(errors) > 10:
            print(f"  ... and {len(errors) - 10} more")
        return False, errors
    else:
        print("✓ All verifiers passed!")
        return True, {}


async def main():
    parser = argparse.ArgumentParser(description="Import tasks from a JSON file")
    parser.add_argument("json_file", help="Path to the JSON file containing tasks")
    parser.add_argument(
        "--project-key",
        "-p",
        help="Optional project key to associate with the tasks",
        default=None,
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Skip confirmation prompt and import automatically",
    )
    parser.add_argument(
        "--skip-sanity-check",
        action="store_true",
        help="Skip the verifier sanity check (not recommended)",
    )
    parser.add_argument(
        "--sanity-check-only",
        action="store_true",
        help="Only run the sanity check without importing tasks",
    )

    args = parser.parse_args()

    # Validate conflicting flags
    if args.skip_sanity_check and args.sanity_check_only:
        parser.error("Cannot use --skip-sanity-check and --sanity-check-only together")

    # Load and parse the JSON file
    try:
        with open(args.json_file, "r", encoding="utf-8") as f:
            tasks_data = json.load(f)
    except FileNotFoundError:
        print(f"Error: File '{args.json_file}' not found")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in '{args.json_file}': {e}")
        sys.exit(1)

    # Extract task information and validate verifier_func
    task_count = len(tasks_data)
    task_keys = []
    missing_verifier = []
    tasks_with_output_schema = []
    for task_data in tasks_data:
        task_key = task_data.get("key") or task_data.get("id")
        if task_key:
            task_keys.append(task_key)
        else:
            task_keys.append("(no key)")

        # Check for verifier_func
        verifier_code = task_data.get("verifier_func") or task_data.get("verifier_code")
        if not verifier_code:
            missing_verifier.append(task_key or "(no key)")

        # Check for output_json_schema
        if task_data.get("output_json_schema"):
            tasks_with_output_schema.append(task_key or "(no key)")

    # Validate all tasks have verifier_func
    if missing_verifier:
        print(f"✗ Error: {len(missing_verifier)} task(s) missing verifier_func:")
        for key in missing_verifier[:10]:  # Show first 10
            print(f"  - {key}")
        if len(missing_verifier) > 10:
            print(f"  ... and {len(missing_verifier) - 10} more")
        print("\nAll tasks must have a verifier_func to be imported.")
        sys.exit(1)

    # Get account info
    account = await fleet.env.account_async()

    # Print summary
    print(f"Importing to team: {account.team_name}")
    print(f"\nFound {task_count} task(s) in '{args.json_file}':")
    print("\nTask keys:")
    for i, key in enumerate(task_keys, 1):
        print(f"  {i}. {key}")

    if args.project_key:
        print(f"\nProject key: {args.project_key}")
    else:
        print("\nProject key: (none)")

    # Load tasks as Task objects
    client = fleet.AsyncFleet()
    tasks = []
    print("\nLoading tasks...")
    for task_data in tasks_data:
        try:
            task = await client.load_task_from_json(
                task_data, raise_on_verifier_error=True
            )
            tasks.append(task)
        except Exception as e:
            task_key = task_data.get("key") or task_data.get("id", "unknown")
            print(f"✗ Failed to load task {task_key}: {e}")
            sys.exit(1)
    print(f"✓ Loaded {len(tasks)} tasks")

    # Run sanity check (unless skipped)
    already_confirmed = False  # Track if user already confirmed import
    if not args.skip_sanity_check:
        success, errors = await run_verifier_sanity_check(tasks, client)

        # If only doing sanity check, exit here
        if args.sanity_check_only:
            if success:
                print("\n✓ Sanity check complete! (--sanity-check-only)")
                print("Tasks are ready to import.")
                sys.exit(0)
            else:
                print("\n✗ Sanity check failed (--sanity-check-only)")
                print("Fix the verifiers and try again.")
                sys.exit(1)

        # Handle partial failures
        if not success:
            # Filter out failed tasks
            failed_keys = set(errors.keys())
            passed_tasks = [t for t in tasks if t.key not in failed_keys]

            print("\n" + "=" * 60)
            print("SANITY CHECK RESULTS")
            print("=" * 60)
            print(f"Passed: {len(passed_tasks)}/{len(tasks)} tasks")
            print(f"Failed: {len(failed_keys)}/{len(tasks)} tasks")

            if len(passed_tasks) == 0:
                print("\n✗ No tasks passed the sanity check.")
                print("Fix the verifiers and try again.")
                sys.exit(1)

            # Prompt user to import only passed tasks
            if not args.yes:
                print("\nWould you like to import only the tasks that passed?")
                response = input("Type 'YES' to import passed tasks only: ")
                if response != "YES":
                    print("Import cancelled.")
                    sys.exit(0)
                already_confirmed = True  # User already confirmed import
            else:
                print("\n⚠️  Auto-importing only tasks that passed (--yes flag)")

            # Update tasks list and tasks_data to only include passed tasks
            tasks = passed_tasks
            passed_keys = {t.key for t in passed_tasks}
            tasks_data = [td for td in tasks_data if td.get("key") in passed_keys]
            # Also filter tasks_with_output_schema
            tasks_with_output_schema = [
                k for k in tasks_with_output_schema if k in passed_keys
            ]

            print(f"\nProceeding with {len(tasks)} tasks that passed sanity check")
    else:
        print("\n⚠️  Skipping sanity check (--skip-sanity-check)")

    # Confirmation prompt (unless --yes flag is provided or already confirmed)
    if not args.yes and not already_confirmed:
        print("\n" + "=" * 60)
        response = input("Type 'YES' to proceed with import: ")
        if response != "YES":
            print("Import cancelled.")
            sys.exit(0)

    # Import tasks
    print("\nImporting tasks...")
    try:
        # If tasks were filtered, write to a temporary file for import
        if len(tasks_data) < task_count:
            # Create temporary file with filtered tasks
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False, encoding="utf-8"
            ) as temp_file:
                json.dump(tasks_data, temp_file, indent=2, ensure_ascii=False)
                temp_filename = temp_file.name

            try:
                results = await fleet.import_tasks_async(
                    temp_filename, project_key=args.project_key
                )
            finally:
                # Clean up temporary file
                os.unlink(temp_filename)
        else:
            # Import from original file if no filtering occurred
            results = await fleet.import_tasks_async(
                args.json_file, project_key=args.project_key
            )

        # Print success summary
        print("\n" + "=" * 60)
        print("IMPORT COMPLETE")
        print("=" * 60)
        print(f"✓ Successfully imported {len(results)} task(s)")

        if args.project_key:
            print(f"✓ Associated with project: {args.project_key}")

        print(f"✓ Team: {account.team_name}")

        # Print HUGE warning if any tasks have output_json_schema
        if tasks_with_output_schema:
            print("\n")
            print("!" * 80)
            print("!" * 80)
            print("!" * 80)
            print(
                "!!!                                                                          !!!"
            )
            print(
                "!!!                          ⚠️  WARNING WARNING WARNING  ⚠️                          !!!"
            )
            print(
                "!!!                                                                          !!!"
            )
            print(
                f"!!!  {len(tasks_with_output_schema)} TASK(S) HAVE OUTPUT_JSON_SCHEMA THAT NEED MANUAL COPYING!  !!!"
            )
            print(
                "!!!                                                                          !!!"
            )
            print(
                "!!!  The output_json_schema field is NOT automatically imported!            !!!"
            )
            print(
                "!!!  You MUST manually copy the output schemas to each task!                !!!"
            )
            print(
                "!!!                                                                          !!!"
            )
            print("!" * 80)
            print("!" * 80)
            print("!" * 80)
            print("\nTasks with output_json_schema:")
            for i, key in enumerate(tasks_with_output_schema[:20], 1):
                print(f"  {i}. {key}")
            if len(tasks_with_output_schema) > 20:
                print(f"  ... and {len(tasks_with_output_schema) - 20} more")
            print("\n⚠️  REMEMBER TO MANUALLY COPY OUTPUT SCHEMAS! ⚠️\n")
    except Exception as e:
        print(f"\n✗ Error importing tasks: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
