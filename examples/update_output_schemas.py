"""
Update existing Fleet tasks with their output_json_schema fields.
This script reads a JSON file and updates the corresponding tasks in the database.

Requirements:
    pip install supabase

Environment variables:
    SUPABASE_URL: Your Supabase project URL
    SUPABASE_KEY: Your Supabase service role key
"""
import json
import os
import sys
from supabase import create_client, Client

# Configuration
TASKS_PATH = "/Users/andrewstelmach/Desktop/template-gen/output/faps_5_stories_200.json"
PROJECT_KEY = "apollo_templated_faps_200"

# Supabase credentials
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://ehefoavidbttssbleuyv.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImVoZWZvYXZpZGJ0dHNzYmxldXl2Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTY4Nzg5ODYyMiwiZXhwIjoyMDAzNDc0NjIyfQ.lQRJ0hBuuvK1YLplS2zk_2n9MB1dJV1vv9OWHVOoQQ8")

# Initialize Supabase client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


def main():
    # Load tasks from JSON
    print(f"Loading tasks from {TASKS_PATH}...")
    with open(TASKS_PATH, 'r') as f:
        tasks_data = json.load(f)

    task_list = tasks_data if isinstance(tasks_data, list) else tasks_data.get('task_pairs', [])

    if not task_list:
        print("No tasks found")
        sys.exit(1)

    print(f"Found {len(task_list)} tasks in JSON file")

    # Filter tasks that have output_json_schema
    tasks_with_schema = [
        task for task in task_list 
        if "output_json_schema" in task and task["output_json_schema"] is not None
    ]

    print(f"Found {len(tasks_with_schema)} tasks with output_json_schema")

    if not tasks_with_schema:
        print("No tasks with output_json_schema to update")
        sys.exit(0)

    # Update each task
    updated_count = 0
    not_found_count = 0
    error_count = 0

    for i, task in enumerate(tasks_with_schema, 1):
        task_key = task.get("key")
        if not task_key:
            print(f"  ⚠ Task {i} has no key, skipping")
            error_count += 1
            continue

        output_schema = task["output_json_schema"]

        try:
            # Check if task exists
            result = supabase.table("eval_tasks").select("id, key").eq("key", task_key).execute()
            
            if not result.data or len(result.data) == 0:
                print(f"  ✗ Task not found: {task_key}")
                not_found_count += 1
                continue

            # Update the task with output_json_schema
            update_result = supabase.table("eval_tasks").update({
                "output_json_schema": output_schema
            }).eq("key", task_key).execute()

            if update_result.data:
                updated_count += 1
                if updated_count % 10 == 0:
                    print(f"  Updated {updated_count}/{len(tasks_with_schema)} tasks...")
            else:
                print(f"  ✗ Failed to update: {task_key}")
                error_count += 1

        except Exception as e:
            print(f"  ✗ Error updating {task_key}: {e}")
            error_count += 1

    # Summary
    print("\n" + "=" * 60)
    print("UPDATE COMPLETE")
    print("=" * 60)
    print(f"✓ Successfully updated: {updated_count}")
    if not_found_count > 0:
        print(f"✗ Tasks not found: {not_found_count}")
    if error_count > 0:
        print(f"✗ Errors: {error_count}")
    print(f"Total tasks processed: {len(tasks_with_schema)}")


if __name__ == "__main__":
    main()
