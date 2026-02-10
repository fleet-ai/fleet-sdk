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
        help="Optional list of task keys to export (comma-separated)",
        default=None,
    )
    parser.add_argument(
        "--task-project-key",
        "-tpk",
        help="Optional task project key to filter tasks",
        default=None,
    )
    parser.add_argument(
        "--env-key",
        "-e",
        help="Optional environment key to filter tasks",
        default=None,
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Output JSON filename (defaults to {team_id}.json)",
        default=None,
    )
    parser.add_argument(
        "--skip-missing-verifiers",
        "-s",
        action="store_true",
        help="Skip tasks missing verifier_func instead of erroring",
    )

    args = parser.parse_args()

    # Validate that only one filter is specified
    filters_specified = sum(
        [
            args.project_key is not None,
            args.task_keys is not None,
            args.task_project_key is not None,
            args.env_key is not None,
        ]
    )

    if filters_specified > 1:
        parser.error(
            "Cannot specify multiple filters. Use only one of --project-key, --task-keys, --task-project-key, or --env-key."
        )

    # Get account info
    account = fleet.env.account()
    print(f"Exporting from team: {account.team_name}")

    # Load tasks
    if args.project_key:
        print(f"Loading tasks from project: {args.project_key}")
        tasks = fleet.load_tasks(project_key=args.project_key)
    elif args.task_keys:
        # Split comma-separated task keys and strip whitespace
        task_keys_list = [key.strip() for key in args.task_keys.split(",")]
        print(
            f"Loading {len(task_keys_list)} specific task(s): {', '.join(task_keys_list)}"
        )
        tasks = fleet.load_tasks(keys=task_keys_list)
    elif args.task_project_key:
        print(f"Loading tasks from task project: {args.task_project_key}")
        tasks = fleet.load_tasks(task_project_key=args.task_project_key)
    elif args.env_key:
        print(f"Loading tasks from environment: {args.env_key}")
        tasks = fleet.load_tasks(env_key=args.env_key)
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
        if args.skip_missing_verifiers:
            print(
                f"\n⚠ Skipping {len(missing_verifier)} task(s) missing verifier_func:"
            )
            for key in missing_verifier[:10]:  # Show first 10
                print(f"  - {key}")
            if len(missing_verifier) > 10:
                print(f"  ... and {len(missing_verifier) - 10} more")
            # Filter out tasks without verifiers
            tasks = [task for task in tasks if task.verifier_func]
            print(f"\n{len(tasks)} task(s) remaining after filtering")
            if not tasks:
                raise ValueError(
                    "No tasks remaining after filtering. Nothing to export."
                )
        else:
            print(f"\n✗ Error: {len(missing_verifier)} task(s) missing verifier_func:")
            for key in missing_verifier[:10]:  # Show first 10
                print(f"  - {key}")
            if len(missing_verifier) > 10:
                print(f"  ... and {len(missing_verifier) - 10} more")
            raise ValueError(
                "All tasks must have a verifier_func. Cannot export tasks without verifiers."
            )
    else:
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
