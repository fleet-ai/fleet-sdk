import argparse
import json
import fleet
from dotenv import load_dotenv

load_dotenv()


def main():
    parser = argparse.ArgumentParser(description="Export tasks to a JSON file")
    parser.add_argument(
        "--project-key",
        "-p",
        help="Optional project key to filter tasks",
        default=None,
    )
    parser.add_argument(
        "--task-keys",
        "-t",
        nargs="+",
        help="Optional list of task keys to export (space-separated)",
        default=None,
    )
    parser.add_argument(
        "--task-project-key",
        "-tpk",
        help="Optional task project key to filter tasks",
        default=None,
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Output JSON filename (defaults to {team_id}.json)",
        default=None,
    )

    args = parser.parse_args()

    # Validate that only one filter is specified
    filters_specified = sum(
        [
            args.project_key is not None,
            args.task_keys is not None,
            args.task_project_key is not None,
        ]
    )

    if filters_specified > 1:
        parser.error(
            "Cannot specify multiple filters. Use only one of --project-key, --task-keys, or --task-project-key."
        )

    # Get account info
    account = fleet.env.account()
    print(f"Exporting from team: {account.team_name}")

    # Load tasks
    if args.project_key:
        print(f"Loading tasks from project: {args.project_key}")
        tasks = fleet.load_tasks(project_key=args.project_key)
    elif args.task_keys:
        print(
            f"Loading {len(args.task_keys)} specific task(s): {', '.join(args.task_keys)}"
        )
        tasks = fleet.load_tasks(keys=args.task_keys)
    elif args.task_project_key:
        print(f"Loading tasks from task project: {args.task_project_key}")
        tasks = fleet.load_tasks(task_project_key=args.task_project_key)
    else:
        print("Loading all tasks")
        tasks = fleet.load_tasks()

    print(f"\nFound {len(tasks)} task(s)")

    # Validate that all tasks have verifier_func
    print("Validating tasks have verifier_func...")
    missing_verifier = []
    for task in tasks:
        if not task.verifier_func:
            missing_verifier.append(task.key)

    if missing_verifier:
        print(f"\n✗ Error: {len(missing_verifier)} task(s) missing verifier_func:")
        for key in missing_verifier[:10]:  # Show first 10
            print(f"  - {key}")
        if len(missing_verifier) > 10:
            print(f"  ... and {len(missing_verifier) - 10} more")
        raise ValueError(
            "All tasks must have a verifier_func. Cannot export tasks without verifiers."
        )

    print("✓ All tasks have verifier_func")

    # Determine output filename
    output_file = args.output or f"{account.team_id}.json"

    # Export to JSON
    print(f"\nExporting to: {output_file}")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(
            [task.model_dump() for task in tasks],
            f,
            indent=2,
            ensure_ascii=False,
        )

    print(f"✓ Successfully exported {len(tasks)} task(s) to {output_file}")


if __name__ == "__main__":
    main()
