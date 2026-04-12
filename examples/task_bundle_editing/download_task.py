#!/usr/bin/env python3
"""
Download a task to a local bundle directory compatible with upload_task.py.

Usage:
    python download_task.py --task-key <key>
    python download_task.py --task-key <key> --output-dir ./my_task

Creates:
    <task-key>/
      task.json      # task metadata, prompt, verifier (upload-compatible)
      files/         # extracted data files from seed tar (if any)

Requires: FLEET_API_KEY env var (or --api-key)
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

DEFAULT_BASE_URL = "https://orchestrator.fleetai.com"


def get_api_base() -> str:
    base = os.environ.get("FLEET_BASE_URL", DEFAULT_BASE_URL).rstrip("/")
    return f"{base}/v1"


def headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def fetch_task(api_key: str, task_key: str) -> dict:
    """GET /v1/tasks/{task_key} → full task JSON from API."""
    print(f"\n1. Fetching task: {task_key}")
    resp = requests.get(
        f"{get_api_base()}/tasks/{task_key}",
        headers=headers(api_key),
    )
    if not resp.ok:
        print(f"   ERROR {resp.status_code}: {resp.text[:500]}")
        resp.raise_for_status()
    task = resp.json()
    print(f"   Environment: {task['environment_id']}")
    print(f"   Version:     {task.get('version')}")
    print(f"   Prompt:      {len(task['prompt'])} chars")
    print(f"   Verifier:    {'yes' if task.get('verifier') else 'no'}")
    print(f"   data_id:     {task.get('data_id') or '(none)'}")
    return task


def to_bundle_json(task: dict) -> dict:
    """Convert API task response to the minimal task.json format for upload_task.py."""
    bundle = {
        "key": task["key"],
        "prompt": task["prompt"],
        "environment_id": task["environment_id"],
        "version": task.get("version"),
    }
    if task.get("metadata"):
        bundle["metadata"] = task["metadata"]
    if task.get("verifier") and task["verifier"].get("code"):
        bundle["verifier"] = {
            "code": task["verifier"]["code"],
        }
        if task["verifier"].get("comment"):
            bundle["verifier"]["comment"] = task["verifier"]["comment"]
    return bundle


def download_seed_tar(api_key: str, task: dict, files_dir: Path) -> bool:
    """Download and extract the seed tar via presigned URL from the API.

    Uses POST /v1/seeds/{data_key}/{env_key}/download-url to get a
    presigned S3 URL, then downloads and extracts the tar.  No AWS
    credentials required — only the Fleet API key.

    Returns True if files were extracted, False on any failure (so the
    caller can fall back to the legacy file-sets download).
    """
    data_id = task.get("data_id")
    env_key = task.get("environment_id")

    if not data_id:
        return False

    print(f"\n2. Downloading seed tar...")
    print(f"   data_id:      {data_id}")

    # Check extraction dependencies
    for cmd in ("zstd", "tar"):
        if not shutil.which(cmd):
            print(f"   WARNING: '{cmd}' not installed, skipping seed tar download.")
            return False

    # Get presigned download URL from the API
    resp = requests.post(
        f"{get_api_base()}/seeds/{data_id}/{env_key}/download-url",
        headers=headers(api_key),
    )
    if resp.status_code == 404:
        print(f"   No seed tar found via API, falling back to file-sets.")
        return False
    if not resp.ok:
        print(f"   WARNING: download-url failed ({resp.status_code}): {resp.text[:200]}")
        return False

    download_info = resp.json()
    presigned_url = download_info["url"]
    print(f"   version:      {download_info['version']}")
    print(f"   s3_key:       {download_info['s3_key']}")

    with tempfile.NamedTemporaryFile(suffix=".tar.zst", delete=False) as tmp:
        tar_path = tmp.name

    try:
        # Download via presigned URL
        dl_resp = requests.get(presigned_url)
        if not dl_resp.ok:
            print(f"   WARNING: S3 download failed ({dl_resp.status_code}), falling back to file-sets.")
            return False

        Path(tar_path).write_bytes(dl_resp.content)
        tar_size = len(dl_resp.content)
        print(f"   Downloaded {tar_size:,} bytes")

        # Extract (two-step to avoid pipe issues on macOS)
        files_dir.mkdir(parents=True, exist_ok=True)
        plain_tar = tar_path + ".tar"
        result = subprocess.run(
            ["zstd", "-d", "-o", plain_tar, tar_path],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"   WARNING: zstd decompression failed, falling back to file-sets.")
            os.unlink(plain_tar) if os.path.exists(plain_tar) else None
            return False
        result = subprocess.run(
            ["tar", "xf", plain_tar, "-C", str(files_dir)],
            capture_output=True,
            text=True,
        )
        os.unlink(plain_tar)
        if result.returncode != 0:
            print(f"   WARNING: tar extraction failed, falling back to file-sets.")
            return False

        file_count = sum(1 for _ in files_dir.rglob("*") if _.is_file())
        print(f"   Extracted {file_count} files to {files_dir}/")
        return True

    finally:
        os.unlink(tar_path)


def download_file_set(api_key: str, task: dict, files_dir: Path) -> bool:
    """Download files via the legacy file-sets API (fallback for old tasks).

    Returns True if files were downloaded, False if no file-set found.
    """
    env_vars = task.get("env_variables") or {}
    file_set_key = env_vars.get("TASK_KEY", task["key"])

    print(f"\n2. Fetching file-set: {file_set_key} (legacy)")
    resp = requests.post(
        f"{get_api_base()}/file-sets/{file_set_key}/download-urls",
        headers=headers(api_key),
        json={"expires_in": 3600},
    )
    if resp.status_code == 404:
        print("   No file-set found.")
        return False
    if not resp.ok:
        print(f"   ERROR {resp.status_code}: {resp.text[:500]}")
        resp.raise_for_status()

    urls = resp.json().get("urls", [])
    if not urls:
        print("   File-set is empty.")
        return False

    print(f"   Found {len(urls)} files")
    files_dir.mkdir(parents=True, exist_ok=True)

    for item in urls:
        filename = item["filename"]
        url = item["url"]
        local_path = files_dir / filename
        local_path.parent.mkdir(parents=True, exist_ok=True)

        print(f"   Downloading: {filename}")
        file_resp = requests.get(url)
        file_resp.raise_for_status()
        local_path.write_bytes(file_resp.content)
        print(f"     -> {len(file_resp.content):,} bytes")

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Download a task to a local bundle directory"
    )
    parser.add_argument("--task-key", required=True, help="Task key to download")
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory (default: ./<task-key>)",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("FLEET_API_KEY"),
        help="API key (default: FLEET_API_KEY env var)",
    )
    args = parser.parse_args()

    if not args.api_key:
        print("Error: FLEET_API_KEY env var or --api-key required")
        sys.exit(1)

    output_dir = Path(args.output_dir) if args.output_dir else Path(args.task_key)
    if output_dir.exists():
        print(f"Error: {output_dir} already exists. Remove it or use --output-dir.")
        sys.exit(1)

    output_dir.mkdir(parents=True)
    files_dir = output_dir / "files"

    print(f"Output directory: {output_dir}")

    # Step 1: Fetch task from API
    task = fetch_task(args.api_key, args.task_key)

    # Step 2: Download files — try seed tar first, fall back to file-sets
    has_files = False
    if task.get("data_id"):
        has_files = download_seed_tar(args.api_key, task, files_dir)
    if not has_files:
        has_files = download_file_set(args.api_key, task, files_dir)
    if not has_files:
        print("\n2. No data files for this task.")

    # Step 3: Save task.json in upload-compatible format
    bundle = to_bundle_json(task)
    task_path = output_dir / "task.json"
    task_path.write_text(json.dumps(bundle, indent=2) + "\n")
    print(f"\n3. Saved task.json: {task_path}")

    file_count = sum(1 for _ in files_dir.rglob("*") if _.is_file()) if files_dir.exists() else 0
    print(f"\n-- Download complete --")
    print(f"   Bundle:  {output_dir}/")
    print(f"   Task:    {task_path}")
    print(f"   Files:   {file_count}")
    print(f"\n   To re-upload: python upload_task.py --dir {output_dir} --env-version {task.get('version', 'VERSION')}")


if __name__ == "__main__":
    main()
