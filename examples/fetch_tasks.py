import argparse
import asyncio
import json
import sys
from typing import List, Dict, Any, Optional, Tuple
import fleet
from dotenv import load_dotenv

load_dotenv()


async def fetch_task(
    task_key: str, semaphore: asyncio.Semaphore
) -> Tuple[str, Optional[Dict[str, Any]], Optional[str]]:
    """
    Fetch a single task from the Fleet API.

    Args:
        task_key: Task key to fetch
        semaphore: Semaphore to limit concurrent requests

    Returns:
        Tuple of (task_key, task_data_dict, error_message)
    """
    async with semaphore:
        try:
            # Use load_tasks with keys parameter to get Task objects
            tasks = await fleet.load_tasks_async(keys=[task_key])
            if tasks:
                task = tasks[0]
                # Convert to dict using model_dump() like export_tasks.py does
                return task_key, task.model_dump(), None
            else:
                return task_key, None, "Task not found"
        except Exception as e:
            error_msg = f"{type(e).__name__}: {str(e)}"
            return task_key, None, error_msg


async def fetch_tasks_batch(
    task_keys: List[str], max_concurrent: int = 20
) -> Dict[str, Dict[str, Any]]:
    """
    Fetch multiple tasks concurrently from the Fleet API.

    Args:
        task_keys: List of task keys to fetch
        max_concurrent: Maximum number of concurrent requests

    Returns:
        Dictionary mapping task_key to task data
    """
    print(f"\nFetching {len(task_keys)} task(s) from Fleet API...")
    print(f"Max concurrent requests: {max_concurrent}")

    semaphore = asyncio.Semaphore(max_concurrent)

    # Fetch all tasks concurrently
    results = await asyncio.gather(
        *[fetch_task(key, semaphore) for key in task_keys],
        return_exceptions=True,
    )

    # Process results
    fetched_tasks = {}
    errors = []

    for result in results:
        if isinstance(result, Exception):
            errors.append(f"Unexpected error: {result}")
            continue

        task_key, task_data, error = result

        if error:
            errors.append(f"{task_key}: {error}")
            print(f"  ✗ {task_key}: {error}")
        elif task_data:
            # Task data is already a dict from model_dump()
            fetched_tasks[task_key] = task_data
            print(f"  ✓ {task_key}")

    print(f"\n✓ Successfully fetched {len(fetched_tasks)} task(s)")

    if errors:
        print(f"\n⚠ {len(errors)} error(s) occurred:")
        for error in errors[:10]:  # Show first 10
            print(f"  - {error}")
        if len(errors) > 10:
            print(f"  ... and {len(errors) - 10} more")

    return fetched_tasks


async def main():
    parser = argparse.ArgumentParser(
        description="Fetch tasks from Fleet API and update JSON file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Fetch tasks and update in-place
  %(prog)s tasks.json

  # Fetch tasks and save to a new file
  %(prog)s tasks.json --output updated_tasks.json

  # Limit concurrent requests
  %(prog)s tasks.json --max-concurrent 10
        """,
    )

    parser.add_argument("json_file", help="Path to JSON file containing tasks")
    parser.add_argument(
        "--output",
        "-o",
        help="Path to output JSON file (defaults to overwriting input)",
        default=None,
    )
    parser.add_argument(
        "--max-concurrent",
        "-c",
        type=int,
        default=20,
        help="Maximum number of concurrent API requests (default: 20)",
    )

    args = parser.parse_args()

    # Load JSON file
    print(f"Reading tasks from: {args.json_file}")
    try:
        with open(args.json_file, "r", encoding="utf-8") as f:
            tasks_data = json.load(f)
    except FileNotFoundError:
        print(f"✗ Error: File '{args.json_file}' not found")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"✗ Error: Invalid JSON in '{args.json_file}': {e}")
        sys.exit(1)

    if not isinstance(tasks_data, list):
        print("✗ Error: JSON file must contain an array of tasks")
        sys.exit(1)

    print(f"Found {len(tasks_data)} task(s) in file")

    # Extract task keys
    task_keys = []
    missing_keys = []

    for i, task in enumerate(tasks_data):
        task_key = task.get("key") or task.get("id")
        if task_key:
            task_keys.append(task_key)
        else:
            missing_keys.append(f"Task at index {i}")

    if missing_keys:
        print(f"\n⚠ Warning: {len(missing_keys)} task(s) missing key/id:")
        for key in missing_keys[:10]:
            print(f"  - {key}")
        if len(missing_keys) > 10:
            print(f"  ... and {len(missing_keys) - 10} more")

    if not task_keys:
        print("\n✗ Error: No valid task keys found in JSON file")
        sys.exit(1)

    print(f"\nExtracted {len(task_keys)} task key(s)")

    # Get account info
    account = await fleet.env.account_async()
    print(f"Fetching from team: {account.team_name}")

    # Fetch tasks from API
    fetched_tasks = await fetch_tasks_batch(task_keys, args.max_concurrent)

    if not fetched_tasks:
        print("\n✗ Error: No tasks were successfully fetched")
        sys.exit(1)

    # Update tasks in the original data
    updated_count = 0
    not_found = []

    print("\nUpdating task data...")
    for i, task in enumerate(tasks_data):
        task_key = task.get("key") or task.get("id")

        if task_key in fetched_tasks:
            # Replace entire task with fetched data
            tasks_data[i] = fetched_tasks[task_key]
            updated_count += 1
        else:
            not_found.append(task_key or f"index {i}")

    print(f"✓ Updated {updated_count} task(s)")

    if not_found:
        print(f"\n⚠ Warning: {len(not_found)} task(s) not fetched:")
        for key in not_found[:10]:
            print(f"  - {key}")
        if len(not_found) > 10:
            print(f"  ... and {len(not_found) - 10} more")

    # Write output
    output_file = args.output or args.json_file
    print(f"\nWriting updated tasks to: {output_file}")

    try:
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(tasks_data, f, indent=2, ensure_ascii=False)
        print(f"✓ Successfully wrote {len(tasks_data)} task(s) to '{output_file}'")
    except Exception as e:
        print(f"✗ Error writing output file: {e}")
        sys.exit(1)

    # Summary
    print("\n" + "=" * 60)
    print("Summary:")
    print(f"  Total tasks in file: {len(tasks_data)}")
    print(f"  Successfully fetched: {len(fetched_tasks)}")
    print(f"  Updated in file: {updated_count}")
    print(f"  Failed to fetch: {len(task_keys) - len(fetched_tasks)}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())

