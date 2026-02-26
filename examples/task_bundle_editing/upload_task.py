#!/usr/bin/env python3
"""
Upload a task bundle (task.json + files/) as a new task, then launch a job.

Usage:
    # Auto-generate key, upload, and launch job:
    python upload_task.py --dir ./my_task

    # Explicit key:
    python upload_task.py --dir ./my_task --key my_custom_key

    # Skip job launch:
    python upload_task.py --dir ./my_task --no-launch-job

    # Custom pass_k:
    python upload_task.py --dir ./my_task --pass-k 3

Steps:
  1. Validates the bundle (same checks as validate_task.py)
  2. Checks task key doesn't already exist on server
  3. Uploads files (creates file-set, gets presigned upload URLs, POSTs files)
  4. Creates the task via POST /v1/tasks
  5. Launches a job via POST /v1/jobs (unless --no-launch-job)

Requires: FLEET_API_KEY env var (or --api-key)
"""

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from validate_task import validate

DEFAULT_BASE_URL = "https://orchestrator.fleetai.com"

DEFAULT_MODELS = [
    "google/gemini-3.1-pro-preview",
    "anthropic/claude-opus-4.6",
    "openai/gpt-5.2",
]


def get_api_base() -> str:
    base = os.environ.get("FLEET_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    return f"{base}/v1"


def headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def resolve_team_id(api_key: str) -> str:
    """GET /v1/account → team_id for this API key."""
    resp = requests.get(f"{get_api_base()}/account", headers=headers(api_key))
    if not resp.ok:
        print(f"   ERROR resolving team: {resp.status_code}: {resp.text[:500]}")
        resp.raise_for_status()
    account = resp.json()
    team_id = account["team_id"]
    team_name = account.get("team_name", "unknown")
    print(f"   Authenticated as team: {team_name} ({team_id})")
    return team_id


def check_task_exists(api_key: str, key: str) -> bool:
    """GET /v1/tasks/{key} — returns True if the task already exists."""
    resp = requests.get(f"{get_api_base()}/tasks/{key}", headers=headers(api_key))
    return resp.status_code == 200


def upload_files(
    api_key: str,
    new_key: str,
    files_dir: Path,
    allow_overwrite: bool = False,
) -> None:
    """Create file-set + upload files via presigned URLs."""
    all_files = [p for p in files_dir.rglob("*") if p.is_file()]
    if not all_files:
        print("\n3. No files to upload, skipping file-set creation.")
        return

    filenames = [str(p.relative_to(files_dir)) for p in all_files]
    print(f"\n3. Uploading {len(filenames)} files to file-set: {new_key}")

    # Create file-set
    resp = requests.post(
        f"{get_api_base()}/file-sets",
        headers=headers(api_key),
        json={"key": new_key, "description": f"Data files for task {new_key}"},
    )
    if resp.status_code == 409:
        print(f"   File-set '{new_key}' already exists, reusing.")
    elif not resp.ok:
        print(f"   ERROR {resp.status_code}: {resp.text[:500]}")
        resp.raise_for_status()
    else:
        print(f"   Created file-set: {new_key}")

    # Get upload URLs
    resp = requests.post(
        f"{get_api_base()}/file-sets/{new_key}/upload-urls",
        headers=headers(api_key),
        json={"filenames": filenames, "expires_in": 3600},
        params={"allow_overwrite": str(allow_overwrite).lower()},
    )
    if resp.status_code == 409:
        detail = resp.json().get("detail", {})
        existing = detail.get("existing_files", [])
        print(f"\n   ERROR: {len(existing)} file(s) already exist in S3:")
        for f in existing:
            print(f"     - {f}")
        print(f"\n   Use --allow-overwrite to replace them.")
        sys.exit(1)
    resp.raise_for_status()
    upload_data = resp.json()

    # Upload each file via presigned POST
    for item in upload_data["urls"]:
        filename = item["filename"]
        local_path = files_dir / filename
        print(f"   Uploading: {filename}")
        with open(local_path, "rb") as fh:
            upload_resp = requests.post(
                item["url"],
                data=item["fields"],
                files={"file": fh},
            )
        upload_resp.raise_for_status()
        print(f"     -> uploaded ({local_path.stat().st_size} bytes)")


def upload_task(api_key: str, task: dict, new_key: str) -> dict:
    """POST /v1/tasks → create task with new key."""
    print(f"\n4. Creating task with key: {new_key}")
    payload = {
        "key": new_key,
        "prompt": task["prompt"],
        "env_id": task["environment_id"],
        "version": task.get("version"),
        "env_variables": {"TASK_KEY": new_key},
        "metadata": task.get("metadata"),
        "data_id": task.get("data_id"),
        "data_version": task.get("data_version"),
    }
    # Include verifier code if present
    verifier = task.get("verifier")
    if verifier and verifier.get("code"):
        payload["verifier_func"] = verifier["code"]

    resp = requests.post(
        f"{get_api_base()}/tasks",
        headers=headers(api_key),
        json=payload,
    )
    if not resp.ok:
        print(f"   ERROR {resp.status_code}: {resp.text[:500]}")
        resp.raise_for_status()
    result = resp.json()
    print(f"   Created task: {result['key']}")
    return result


def launch_job(api_key: str, task_key: str, models: list[str], pass_k: int) -> dict:
    """POST /v1/jobs → launch a job for the task."""
    print(f"\n5. Launching job for task: {task_key}")
    print(f"   Models: {', '.join(models)}")
    print(f"   pass_k: {pass_k}")
    payload = {
        "task_key": task_key,
        "models": models,
        "pass_k": pass_k,
    }
    resp = requests.post(
        f"{get_api_base()}/jobs",
        headers=headers(api_key),
        json=payload,
    )
    if not resp.ok:
        print(f"   ERROR {resp.status_code}: {resp.text[:500]}")
        resp.raise_for_status()
    result = resp.json()
    job_id = result.get("id", "N/A")
    status = result.get("status", "N/A")
    print(f"   Job launched: {job_id} (status: {status})")
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Upload a task bundle as a new task and launch a job"
    )
    parser.add_argument(
        "--dir", required=True, help="Path to the task bundle directory"
    )
    parser.add_argument(
        "--key",
        help="New task key (default: auto-generated from task.json key + UUID)",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("FLEET_API_KEY"),
        help="API key (default: FLEET_API_KEY env var)",
    )
    parser.add_argument(
        "--team-id",
        help="Team ID override (default: auto-resolved from API key)",
    )
    parser.add_argument(
        "--allow-overwrite",
        action="store_true",
        help="Allow overwriting existing files in S3",
    )
    parser.add_argument(
        "--no-launch-job",
        action="store_true",
        help="Skip launching a job after upload",
    )
    parser.add_argument(
        "--models",
        nargs="+",
        default=DEFAULT_MODELS,
        help=f"Models for the job (default: {' '.join(DEFAULT_MODELS)})",
    )
    parser.add_argument(
        "--pass-k",
        type=int,
        default=1,
        help="pass_k for the job (default: 1)",
    )
    args = parser.parse_args()

    if not args.api_key:
        print("Error: FLEET_API_KEY env var or --api-key required")
        sys.exit(1)

    # Resolve team_id from API key unless overridden
    team_id = args.team_id or resolve_team_id(args.api_key)

    bundle_dir = Path(args.dir)
    if not bundle_dir.is_dir():
        print(f"Error: {bundle_dir} is not a directory")
        sys.exit(1)

    # Load task.json
    task_path = bundle_dir / "task.json"
    if not task_path.exists():
        print(f"Error: {task_path} not found")
        sys.exit(1)

    task = json.loads(task_path.read_text())
    original_key = task.get("key", "")

    # Derive key if not provided
    if args.key:
        new_key = args.key
    else:
        suffix = uuid.uuid4().hex[:8]
        new_key = f"{original_key}_{suffix}"
        print(f"Auto-generated task key: {new_key}")

    # Step 1: Validate
    print("1. Validating bundle...")
    errors = validate(bundle_dir, new_key=new_key)
    if errors:
        print("Bundle validation failed. Fix errors above before uploading.")
        sys.exit(1)

    # Step 2: Check task doesn't already exist on server
    print(f"\n2. Checking if task key '{new_key}' already exists...")
    if check_task_exists(args.api_key, new_key):
        print(
            f"Error: Task with key '{new_key}' already exists. "
            "Use a different --key."
        )
        sys.exit(1)
    print(f"   Key '{new_key}' is available.")

    files_dir = bundle_dir / "files"

    # Step 3: Upload files first (so a failure here doesn't leave a half-created task)
    if files_dir.exists():
        upload_files(args.api_key, new_key, files_dir, allow_overwrite=args.allow_overwrite)
    else:
        print("\n3. No files/ directory, skipping file-set creation.")

    # Step 4: Create the task
    result = upload_task(args.api_key, task, new_key)

    print(f"\n-- Upload complete --")
    print(f"   Original key: {original_key}")
    print(f"   New key:      {new_key}")
    print(f"   Task ID:      {result.get('id', 'N/A')}")

    # Step 5: Launch job (unless --no-launch-job)
    if not args.no_launch_job:
        job_result = launch_job(args.api_key, new_key, args.models, args.pass_k)
        print(f"\n-- Job launched --")
        print(f"   Job ID:  {job_result.get('id', 'N/A')}")
        print(f"   Status:  {job_result.get('status', 'N/A')}")
    else:
        print("\n   Skipping job launch (--no-launch-job)")


if __name__ == "__main__":
    main()
