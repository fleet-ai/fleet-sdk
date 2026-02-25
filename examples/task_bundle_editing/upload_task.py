#!/usr/bin/env python3
"""
Upload a task bundle (task.json + files/) as a new task.

Usage:
    python upload_task.py --dir ./my_task --key my_new_task

Steps:
  1. Validates the bundle (same checks as validate_task.py)
  2. Uploads files first (creates file-set, gets presigned upload URLs, POSTs files)
  3. Creates the task via POST /v1/tasks

Requires: FLEET_API_KEY env var (or --api-key)
"""

import argparse
import json
import os
import sys
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from validate_task import validate

DEFAULT_BASE_URL = "https://orchestrator.fleetai.com"


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


def upload_files(
    api_key: str,
    new_key: str,
    files_dir: Path,
    allow_overwrite: bool = False,
) -> None:
    """Create file-set + upload files via presigned URLs."""
    all_files = [p for p in files_dir.rglob("*") if p.is_file()]
    if not all_files:
        print("\n2. No files to upload, skipping file-set creation.")
        return

    filenames = [str(p.relative_to(files_dir)) for p in all_files]
    print(f"\n2. Uploading {len(filenames)} files to file-set: {new_key}")

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
    print(f"\n3. Creating task with key: {new_key}")
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


def main():
    parser = argparse.ArgumentParser(
        description="Upload a task bundle as a new task"
    )
    parser.add_argument(
        "--dir", required=True, help="Path to the task bundle directory"
    )
    parser.add_argument("--key", required=True, help="New task key")
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

    # Safety: new key must differ from original
    original_key = task.get("key", "")
    if args.key == original_key:
        print(
            f"Error: --key '{args.key}' is the same as the original task key. "
            "Use a different key to avoid overwriting the original."
        )
        sys.exit(1)

    # Step 1: Validate
    print("1. Validating bundle...")
    errors = validate(bundle_dir, new_key=args.key)
    if errors:
        print("Bundle validation failed. Fix errors above before uploading.")
        sys.exit(1)

    files_dir = bundle_dir / "files"

    # Step 2: Upload files first (so a failure here doesn't leave a half-created task)
    if files_dir.exists():
        upload_files(args.api_key, args.key, files_dir, allow_overwrite=args.allow_overwrite)
    else:
        print("\n2. No files/ directory, skipping file-set creation.")

    # Step 3: Create the task
    result = upload_task(args.api_key, task, args.key)

    print(f"\n-- Upload complete --")
    print(f"   Original key: {original_key}")
    print(f"   New key:      {args.key}")
    print(f"   Task ID:      {result.get('id', 'N/A')}")


if __name__ == "__main__":
    main()
