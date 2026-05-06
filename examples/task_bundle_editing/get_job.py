#!/usr/bin/env python3
"""
Get information about a job launched via launch_job.py / upload_task.py.

By default prints job status, per-task pass rates, and per-session results.
Use --transcripts to also dump full transcripts for each session, or
--session-id to fetch a single session transcript directly.

Usage:
    # Job summary (status + per-task pass rates + per-session details):
    python get_job.py --job-id <job_id>

    # Include full transcripts for every session in the job:
    python get_job.py --job-id <job_id> --transcripts

    # Only the transcript for a single session:
    python get_job.py --session-id <session_id>

    # JSON output instead of human-formatted:
    python get_job.py --job-id <job_id> --json

Requires: FLEET_API_KEY env var (or --api-key)
"""

import argparse
import json
import os
import sys

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


def get_job(api_key: str, job_id: str) -> dict:
    """GET /v1/jobs/{job_id} → job metadata + status."""
    resp = requests.get(
        f"{get_api_base()}/jobs/{job_id}", headers=headers(api_key)
    )
    if resp.status_code == 404:
        print(f"   ERROR: Job '{job_id}' not found.")
        sys.exit(1)
    if not resp.ok:
        print(f"   ERROR {resp.status_code}: {resp.text[:500]}")
        resp.raise_for_status()
    return resp.json()


def get_job_sessions(api_key: str, job_id: str) -> dict:
    """GET /v1/sessions/job/{job_id} → sessions grouped by task with stats."""
    resp = requests.get(
        f"{get_api_base()}/sessions/job/{job_id}", headers=headers(api_key)
    )
    if not resp.ok:
        print(f"   ERROR {resp.status_code}: {resp.text[:500]}")
        resp.raise_for_status()
    return resp.json()


def get_session_transcript(api_key: str, session_id: str) -> dict:
    """GET /v1/sessions/{session_id}/transcript → task, instance, verifier, messages."""
    resp = requests.get(
        f"{get_api_base()}/sessions/{session_id}/transcript",
        headers=headers(api_key),
    )
    if resp.status_code == 404:
        print(f"   ERROR: Session '{session_id}' not found.")
        sys.exit(1)
    if not resp.ok:
        print(f"   ERROR {resp.status_code}: {resp.text[:500]}")
        resp.raise_for_status()
    return resp.json()


def print_job_summary(job: dict, sessions: dict) -> None:
    print("\n-- Job --")
    print(f"   ID:         {job.get('id', 'N/A')}")
    print(f"   Name:       {job.get('name', 'N/A')}")
    print(f"   Status:     {job.get('status', 'N/A')}")
    print(f"   Created at: {job.get('created_at', 'N/A')}")

    total_sessions = sessions.get("total_sessions", 0)
    tasks = sessions.get("tasks", []) or []
    print(f"\n-- Sessions ({total_sessions} total across {len(tasks)} task(s)) --")
    for t in tasks:
        task_info = t.get("task") or {}
        key = task_info.get("key") or t.get("task_id") or "(unknown)"
        passed = t.get("passed_sessions", 0)
        total = t.get("total_sessions", 0)
        rate = t.get("pass_rate")
        avg = t.get("average_score")
        rate_str = f"{rate:.0%}" if isinstance(rate, (int, float)) else "N/A"
        avg_str = f"{avg:.3f}" if isinstance(avg, (int, float)) else "N/A"
        print(
            f"\n   Task: {key}"
            f"\n      passed:    {passed}/{total} ({rate_str})"
            f"\n      avg score: {avg_str}"
        )
        for s in t.get("sessions", []) or []:
            sid = s.get("session_id", "?")
            model = s.get("model", "?")
            status = s.get("status", "?")
            steps = s.get("step_count", 0)
            ver = s.get("verifier_execution") or {}
            success = ver.get("success")
            score = ver.get("score")
            success_str = (
                "PASS" if success is True
                else "FAIL" if success is False
                else "—"
            )
            score_str = (
                f"score={score:.3f}" if isinstance(score, (int, float)) else ""
            )
            print(
                f"      • {sid}  [{model}]  status={status}  steps={steps}  "
                f"{success_str} {score_str}".rstrip()
            )


def print_transcript(transcript: dict) -> None:
    task = transcript.get("task") or {}
    inst = transcript.get("instance") or {}
    ver = transcript.get("verifier_execution") or {}
    print(f"\n   Task:     {task.get('key', 'N/A')}")
    print(f"   Instance: {inst.get('id', inst.get('instance_id', 'N/A'))}")
    if ver:
        success = ver.get("success")
        score = ver.get("score")
        print(
            f"   Verifier: success={success}  score={score}  "
            f"time_ms={ver.get('execution_time_ms', 'N/A')}"
        )
    msgs = transcript.get("transcript", []) or []
    print(f"\n   Transcript ({len(msgs)} messages):")
    for i, m in enumerate(msgs):
        role = m.get("role", "?")
        content = m.get("content", "")
        if isinstance(content, list):
            content = json.dumps(content, ensure_ascii=False)
        elif not isinstance(content, str):
            content = str(content)
        first_line = content.replace("\n", " ")[:200]
        print(f"      [{i:>3}] {role}: {first_line}")


def main():
    parser = argparse.ArgumentParser(
        description="Get information about a job (status, sessions, transcripts)"
    )
    parser.add_argument("--job-id", help="Job ID to inspect")
    parser.add_argument(
        "--session-id",
        help="Fetch a single session transcript instead of a job summary",
    )
    parser.add_argument(
        "--transcripts",
        action="store_true",
        help="Also fetch full transcripts for every session in the job",
    )
    parser.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Emit raw JSON instead of human-formatted output",
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
    if not args.job_id and not args.session_id:
        print("Error: --job-id or --session-id required")
        sys.exit(1)

    if args.session_id:
        transcript = get_session_transcript(args.api_key, args.session_id)
        if args.as_json:
            print(json.dumps(transcript, indent=2))
        else:
            print_transcript(transcript)
        return

    job = get_job(args.api_key, args.job_id)
    sessions = get_job_sessions(args.api_key, args.job_id)

    transcripts = None
    if args.transcripts:
        transcripts = {}
        for t in sessions.get("tasks", []) or []:
            for s in t.get("sessions", []) or []:
                sid = s.get("session_id")
                if sid:
                    transcripts[sid] = get_session_transcript(args.api_key, sid)

    if args.as_json:
        out = {"job": job, "sessions": sessions}
        if transcripts is not None:
            out["transcripts"] = transcripts
        print(json.dumps(out, indent=2))
        return

    print_job_summary(job, sessions)
    if transcripts is not None:
        for sid, tr in transcripts.items():
            print(f"\n-- Session {sid} --")
            print_transcript(tr)


if __name__ == "__main__":
    main()
