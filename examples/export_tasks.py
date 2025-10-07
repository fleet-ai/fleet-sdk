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
        "--output",
        "-o",
        help="Output JSON filename (defaults to {team_id}.json)",
        default=None,
    )

    args = parser.parse_args()

    # Get account info
    account = fleet.env.account()
    print(f"Exporting from team: {account.team_name}")

    # Load tasks
    if args.project_key:
        print(f"Loading tasks from project: {args.project_key}")
        tasks = fleet.load_tasks(project_key=args.project_key)
    else:
        print("Loading all tasks")
        tasks = fleet.load_tasks()

    print(f"\nFound {len(tasks)} task(s)")
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
