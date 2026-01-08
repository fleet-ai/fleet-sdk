"""
Export tasks to JSON, excluding tasks from targets marked as 'unused'.

This script filters out tasks whose task_project_target has status='unused',
ensuring that broken/invalid targets don't pollute exports.

Usage:
    python export_tasks_filtered.py --task-project-key my-project
    python export_tasks_filtered.py --project-key my-project --output tasks.json
    python export_tasks_filtered.py --env-key my-env
"""

import argparse
import json
import os
from typing import List, Set

import fleet
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()


def get_unused_target_ids(supabase: Client, team_id: str) -> Set[str]:
    """Fetch all target IDs that have status='unused' for the given team."""
    # Get all task_projects for this team first
    projects_response = (
        supabase.table("task_projects")
        .select("id")
        .eq("team_id", team_id)
        .execute()
    )
    
    if not projects_response.data:
        return set()
    
    project_ids = [p["id"] for p in projects_response.data]
    
    # Get all targets with status='unused' for these projects
    targets_response = (
        supabase.table("task_project_targets")
        .select("id")
        .in_("project_id", project_ids)
        .eq("status", "unused")
        .execute()
    )
    
    if not targets_response.data:
        return set()
    
    return {t["id"] for t in targets_response.data}


def get_task_target_mapping(supabase: Client, task_keys: List[str], team_id: str) -> dict:
    """Fetch task_project_target_id for each task key."""
    if not task_keys:
        return {}
    
    # Batch the queries to avoid hitting limits
    BATCH_SIZE = 100
    mapping = {}
    
    for i in range(0, len(task_keys), BATCH_SIZE):
        batch_keys = task_keys[i:i + BATCH_SIZE]
        response = (
            supabase.table("eval_tasks")
            .select("key, task_project_target_id")
            .in_("key", batch_keys)
            .eq("team_id", team_id)
            .execute()
        )
        
        for row in response.data or []:
            mapping[row["key"]] = row.get("task_project_target_id")
    
    return mapping


def main():
    parser = argparse.ArgumentParser(
        description="Export tasks to JSON, excluding tasks from 'unused' targets"
    )
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
        "--env-key",
        "-e",
        help="Optional environment key to filter tasks",
        default=None,
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Output JSON filename (defaults to {team_id}_filtered.json)",
        default=None,
    )
    parser.add_argument(
        "--include-unused",
        action="store_true",
        help="Include tasks from 'unused' targets (disables filtering)",
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

    # Initialize Supabase client for filtering
    supabase_url = os.getenv("SUPABASE_URL") or os.getenv("NEXT_PUBLIC_SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    
    if not supabase_url or not supabase_key:
        print("⚠ Warning: SUPABASE_URL/SUPABASE_KEY not set - cannot filter by target status")
        print("  Falling back to unfiltered export")
        supabase = None
    else:
        supabase = create_client(supabase_url, supabase_key)

    # Load tasks
    if args.project_key:
        print(f"Loading tasks from project: {args.project_key}")
        tasks = fleet.load_tasks(project_key=args.project_key)
    elif args.task_keys:
        print(f"Loading {len(args.task_keys)} specific task(s): {', '.join(args.task_keys)}")
        tasks = fleet.load_tasks(keys=args.task_keys)
    elif args.task_project_key:
        print(f"Loading tasks from task project: {args.task_project_key}")
        tasks = fleet.load_tasks(task_project_key=args.task_project_key)
    elif args.env_key:
        print(f"Loading tasks from environment: {args.env_key}")
        tasks = fleet.load_tasks(env_key=args.env_key)
    else:
        print("Loading all tasks")
        tasks = fleet.load_tasks()

    print(f"\nFound {len(tasks)} task(s) before filtering")

    # Filter out tasks from unused targets
    filtered_tasks = tasks
    excluded_count = 0
    
    if supabase and not args.include_unused:
        print("\nFiltering out tasks from 'unused' targets...")
        
        # Get unused target IDs
        unused_target_ids = get_unused_target_ids(supabase, account.team_id)
        
        if unused_target_ids:
            print(f"  Found {len(unused_target_ids)} unused target(s)")
            
            # Get task -> target mapping
            task_keys = [t.key for t in tasks]
            task_target_map = get_task_target_mapping(supabase, task_keys, account.team_id)
            
            # Filter tasks
            filtered_tasks = []
            for task in tasks:
                target_id = task_target_map.get(task.key)
                if target_id in unused_target_ids:
                    excluded_count += 1
                else:
                    filtered_tasks.append(task)
            
            print(f"  Excluded {excluded_count} task(s) from unused targets")
        else:
            print("  No unused targets found - all tasks included")
    
    tasks = filtered_tasks
    print(f"\n{len(tasks)} task(s) after filtering")

    # Validate that all tasks have verifier_func
    print("\nValidating tasks have verifier_func...")
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
    output_file = args.output or f"{account.team_id}_filtered.json"

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
    if excluded_count > 0:
        print(f"  ({excluded_count} task(s) excluded from unused targets)")


if __name__ == "__main__":
    main()


