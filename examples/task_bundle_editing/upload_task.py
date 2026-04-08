#!/usr/bin/env python3
"""
Upload a task bundle (task.json + files/) as a new task, then launch a job.

Usage:
    # Auto-generate key, upload, and launch job:
    python upload_task.py --dir ./my_task --env-version v0.0.50

    # Explicit key:
    python upload_task.py --dir ./my_task --key my_custom_key --env-version v0.0.50

    # Skip job launch:
    python upload_task.py --dir ./my_task --env-version v0.0.50 --no-launch-job

    # Custom pass_k:
    python upload_task.py --dir ./my_task --env-version v0.0.50 --pass-k 3

Steps:
  1. Validates the bundle (same checks as validate_task.py)
  2. Checks task key doesn't already exist on server
  3. Packages files/ as seed.tar.zst and uploads via POST /v1/seeds
  4. Creates the task via POST /v1/tasks (with data_id/data_version)
  5. Launches a job via POST /v1/jobs (unless --no-launch-job)

Requires: FLEET_API_KEY env var (or --api-key)
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

# validate_task.py lives alongside this script
sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate_task import validate

DEFAULT_BASE_URL = "https://orchestrator.fleetai.com"

DEFAULT_MODELS = [
    "anthropic/claude-sonnet-4.6",
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
    if resp.status_code == 200:
        return True
    if resp.status_code == 404:
        return False
    print(f"   ERROR checking task existence: {resp.status_code}: {resp.text[:500]}")
    resp.raise_for_status()
    return False  # unreachable, but keeps the type checker happy


def upload_seed_tar(
    api_key: str,
    env_key: str,
    env_version: str,
    files_dir: Path,
    data_key: str,
) -> dict:
    """Package files/ as seed.tar.zst and upload via presigned URL.

    Steps:
      1. Package files/ into a local seed.tar.zst
      2. Request a presigned upload URL from the orchestrator
         (this also registers the data_key in environment_versions)
      3. PUT the tar directly to S3 via the presigned URL

    Returns the upload-url response dict with data_key, env_key, version, s3_key.
    """
    print(f"\n3. Packaging files as seed.tar.zst...")

    # Check dependencies
    for cmd in ("tar", "zstd"):
        if not shutil.which(cmd):
            print(f"   ERROR: '{cmd}' is not installed. Install it and retry.")
            sys.exit(1)

    with tempfile.NamedTemporaryFile(suffix=".tar.zst", delete=False) as tmp:
        tar_path = tmp.name

    try:
        # Package files as tar.zst (piped to avoid holding full tar in memory)
        tar_proc = subprocess.Popen(
            ["tar", "cf", "-", "-C", str(files_dir), "."],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        zstd_proc = subprocess.Popen(
            ["zstd", "-o", tar_path, "-f"],
            stdin=tar_proc.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        tar_proc.stdout.close()
        _, zstd_stderr = zstd_proc.communicate()
        tar_proc.wait()
        if tar_proc.returncode != 0:
            print(f"   ERROR: tar failed (exit {tar_proc.returncode})")
            sys.exit(1)
        if zstd_proc.returncode != 0:
            print(f"   ERROR: zstd failed (exit {zstd_proc.returncode}): {zstd_stderr.decode()[:200]}")
            sys.exit(1)

        tar_size = os.path.getsize(tar_path)
        print(f"   Created seed.tar.zst ({tar_size:,} bytes)")

        # Get presigned upload URL (also registers data_key)
        print(f"   Requesting upload URL for {data_key}/{env_key}...")
        resp = requests.post(
            f"{get_api_base()}/seeds/{data_key}/{env_key}/upload-url",
            headers=headers(api_key),
            json={
                "filename": "seed.tar.zst",
                "env_version": env_version,
            },
        )
        if not resp.ok:
            print(f"   ERROR {resp.status_code}: {resp.text[:500]}")
            resp.raise_for_status()

        upload_info = resp.json()
        presigned_url = upload_info["url"]
        print(f"   Version:  {upload_info['version']}")
        print(f"   S3 key:   {upload_info['s3_key']}")

        # Upload tar directly to S3 via presigned URL
        print(f"   Uploading to S3 ({tar_size:,} bytes)...")
        with open(tar_path, "rb") as fh:
            put_resp = requests.put(
                presigned_url,
                data=fh,
                headers={"Content-Type": "application/octet-stream"},
            )
        if not put_resp.ok:
            print(f"\n   ERROR: S3 upload failed ({put_resp.status_code})")
            print(f"   Re-run this script to retry.")
            sys.exit(1)

        print(f"   Uploaded successfully")
        return upload_info

    finally:
        os.unlink(tar_path)


def create_task(
    api_key: str,
    task: dict,
    new_key: str,
    env_version: str,
    seed_upload: dict | None = None,
) -> dict:
    """POST /v1/tasks → create task with new key.

    If seed_upload is provided, sets data_id/data_version and flexible seed
    env vars so the driver delivers files via seed_map.
    """
    print(f"\n4. Creating task with key: {new_key}")

    if seed_upload:
        env_variables = {
            "FLEET__FLEXIBLE_SEED_SRC": ".",
            "FLEET__FLEXIBLE_SEED_DST": "files",
        }
        data_id = seed_upload["data_key"]
        data_version = seed_upload["version"]
    else:
        env_variables = {}
        data_id = task.get("data_id")
        data_version = task.get("data_version")

    payload = {
        "key": new_key,
        "prompt": task["prompt"],
        "env_id": task["environment_id"],
        "version": env_version,
        "env_variables": env_variables,
        "metadata": task.get("metadata"),
        "data_id": data_id,
        "data_version": data_version,
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
    if seed_upload:
        print(f"   data_id:      {data_id}")
        print(f"   data_version: {data_version}")
    return result


def launch_job(api_key: str, task_key: str, models: list[str], pass_k: int) -> dict:
    """POST /v1/jobs → launch a job for the task."""
    print(f"\n5. Launching job for task: {task_key}")
    print(f"   Models: {', '.join(models)}")
    print(f"   pass_k: {pass_k}")
    payload = {
        "task_keys": [task_key],
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
    job_id = result.get("job_id", result.get("id", "N/A"))
    status = result.get("status", "N/A")
    print(f"   Job launched: {job_id} (status: {status})")
    if job_id != "N/A":
        print(f"   Dashboard:    https://fleetai.com/dashboard/jobs/{job_id}")
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
        help="New task key (default: auto-generated from task.json key + UUID suffix)",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("FLEET_API_KEY"),
        help="API key (default: FLEET_API_KEY env var)",
    )
    parser.add_argument(
        "--env-version",
        default=None,
        help="Environment version (default: from task.json 'version' field)",
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

    # Verify API key is valid
    resolve_team_id(args.api_key)

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

    env_version = args.env_version or task.get("version")
    if not env_version:
        print("Error: --env-version is required (or set 'version' in task.json)")
        sys.exit(1)

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

    # Step 3: Package and upload files as seed tar
    files_dir = bundle_dir / "files"
    seed_upload = None
    has_files = files_dir.is_dir() and any(files_dir.rglob("*"))
    if has_files:
        seed_upload = upload_seed_tar(
            args.api_key,
            env_key=task.get("environment_id", "carlisle"),
            env_version=env_version,
            files_dir=files_dir,
            data_key=new_key,
        )
    else:
        print("\n3. No files/ directory, skipping seed upload.")

    # Step 4: Create the task
    result = create_task(
        args.api_key, task, new_key, env_version, seed_upload=seed_upload,
    )

    print(f"\n-- Upload complete --")
    print(f"   Original key: {original_key}")
    print(f"   New key:      {new_key}")
    print(f"   Task ID:      {result.get('id', 'N/A')}")

    # Step 5: Launch job (unless --no-launch-job)
    if not args.no_launch_job:
        job_result = launch_job(args.api_key, new_key, args.models, args.pass_k)
        job_id = job_result.get("job_id", job_result.get("id", "N/A"))
        print(f"\n-- Job launched --")
        print(f"   Job ID:  {job_id}")
        print(f"   Status:  {job_result.get('status', 'N/A')}")
        if job_id != "N/A":
            print(f"   URL:     https://fleetai.com/dashboard/jobs/{job_id}")
    else:
        print("\n   Skipping job launch (--no-launch-job)")


if __name__ == "__main__":
    main()
