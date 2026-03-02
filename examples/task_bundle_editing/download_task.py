#!/usr/bin/env python3
"""
Download a task and its data files to a local directory.

Usage:
    python download_task.py --task-key <key> --output-dir ./my_task

Creates:
    my_task/
      task.json      # task metadata, prompt, verifier
      files/         # data files from file-set (may be empty)
        notebook.ipynb
        solution.py

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


def download_task(api_key: str, task_key: str, team_id: str | None = None) -> dict:
    """GET /v1/tasks/{task_key} → task JSON."""
    print(f"\n1. Downloading task: {task_key}")
    params = {}
    if team_id:
        params["team_id"] = team_id
    resp = requests.get(
        f"{get_api_base()}/tasks/{task_key}",
        headers=headers(api_key),
        params=params,
    )
    if not resp.ok:
        print(f"   ERROR {resp.status_code}: {resp.text[:500]}")
        resp.raise_for_status()
    task = resp.json()
    print(f"   prompt: {len(task['prompt'])} chars")
    print(f"   environment_id: {task['environment_id']}")
    print(f"   version: {task.get('version')}")
    print(f"   verifier_id: {task.get('verifier_id')}")
    return task


def download_files(api_key: str, task_key: str, dest_dir: Path) -> list[Path]:
    """POST /v1/file-sets/{key}/download-urls → download each file."""
    print(f"\n2. Fetching download URLs for file-set: {task_key}")
    resp = requests.post(
        f"{get_api_base()}/file-sets/{task_key}/download-urls",
        headers=headers(api_key),
        json={"expires_in": 3600},
    )
    if resp.status_code == 404:
        print("   No file-set found for this task key (no data files).")
        return []
    if not resp.ok:
        print(f"   ERROR {resp.status_code}: {resp.text[:500]}")
        resp.raise_for_status()
    data = resp.json()

    urls = data.get("urls", [])
    print(f"   Found {len(urls)} files")

    downloaded = []
    for item in urls:
        filename = item["filename"]
        url = item["url"]
        local_path = dest_dir / filename
        local_path.parent.mkdir(parents=True, exist_ok=True)

        print(f"   Downloading: {filename}")
        file_resp = requests.get(url)
        file_resp.raise_for_status()
        local_path.write_bytes(file_resp.content)
        downloaded.append(local_path)
        print(f"     -> {local_path} ({len(file_resp.content)} bytes)")

    return downloaded


def main():
    parser = argparse.ArgumentParser(
        description="Download a task + data files to a local directory"
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
    parser.add_argument(
        "--team-id",
        help="Team ID override (default: auto-resolved from API key)",
    )
    args = parser.parse_args()

    if not args.api_key:
        print("Error: FLEET_API_KEY env var or --api-key required")
        sys.exit(1)

    # Only pass team_id to task GET if explicitly provided (requires admin).
    # Otherwise, resolve team info just for display.
    if args.team_id:
        team_id = args.team_id
    else:
        resolve_team_id(args.api_key)
        team_id = None

    output_dir = Path(args.output_dir) if args.output_dir else Path(args.task_key)
    output_dir.mkdir(parents=True, exist_ok=True)
    files_dir = output_dir / "files"
    files_dir.mkdir(exist_ok=True)

    print(f"Output directory: {output_dir}")

    # Download task metadata
    task = download_task(args.api_key, args.task_key, team_id=team_id)

    # Save task JSON
    task_path = output_dir / "task.json"
    task_path.write_text(json.dumps(task, indent=2))
    print(f"   Saved to: {task_path}")

    # Download data files — use TASK_KEY env variable as file-set key if available,
    # since the file-set key may differ from the task key (e.g., without version suffix)
    file_set_key = (task.get("env_variables") or {}).get("TASK_KEY", args.task_key)
    downloaded = download_files(args.api_key, file_set_key, files_dir)

    print(f"\n-- Download complete --")
    print(f"   Task JSON: {task_path}")
    print(f"   Files ({len(downloaded)}): {files_dir}")


if __name__ == "__main__":
    main()
