#!/usr/bin/env python3
"""
Launch a job for one or more existing tasks.

Usage:
    # Single task:
    python launch_job.py --task-key my-task

    # Multiple tasks:
    python launch_job.py --task-key task-a task-b task-c

    # Custom models and pass_k:
    python launch_job.py --task-key my-task --models anthropic/claude-opus-4.6 --pass-k 3

Requires: FLEET_API_KEY env var (or --api-key)
"""

import argparse
import os
import sys

import requests

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

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


def verify_tasks_exist(api_key: str, task_keys: list[str]) -> None:
    """Check that all task keys exist on the server."""
    print(f"\n1. Verifying {len(task_keys)} task(s) exist...")
    for key in task_keys:
        resp = requests.get(
            f"{get_api_base()}/tasks/{key}", headers=headers(api_key)
        )
        if resp.status_code == 404:
            print(f"   ERROR: Task '{key}' not found.")
            sys.exit(1)
        if not resp.ok:
            print(f"   ERROR checking task '{key}': {resp.status_code}: {resp.text[:500]}")
            resp.raise_for_status()
        task = resp.json()
        print(f"   {key} (version: {task.get('version')}, env: {task.get('environment_id')})")


def launch_job(
    api_key: str, task_keys: list[str], models: list[str], pass_k: int
) -> dict:
    """POST /v1/jobs → launch a job for the given tasks."""
    print(f"\n2. Launching job...")
    print(f"   Tasks:  {', '.join(task_keys)}")
    print(f"   Models: {', '.join(models)}")
    print(f"   pass_k: {pass_k}")
    payload = {
        "task_keys": task_keys,
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
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Launch a job for existing task(s)"
    )
    parser.add_argument(
        "--task-key",
        nargs="+",
        required=True,
        help="Task key(s) to launch a job for",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("FLEET_API_KEY"),
        help="API key (default: FLEET_API_KEY env var)",
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

    resolve_team_id(args.api_key)

    # Verify all tasks exist before launching
    verify_tasks_exist(args.api_key, args.task_key)

    # Launch the job
    result = launch_job(args.api_key, args.task_key, args.models, args.pass_k)

    job_id = result.get("job_id", result.get("id", "N/A"))
    print(f"\n-- Job launched --")
    print(f"   Job ID:  {job_id}")
    print(f"   Status:  {result.get('status', 'N/A')}")
    if job_id != "N/A":
        print(f"   URL:     https://fleetai.com/dashboard/jobs/{job_id}")


if __name__ == "__main__":
    main()
