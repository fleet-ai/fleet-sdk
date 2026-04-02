#!/usr/bin/env python3
"""
Task Delivery Script — Phased workflow for exporting, diffing, and importing tasks.

Interactive tool designed to be run phase-by-phase with review between each step.

Phases:
  export     Export all prod tasks from source account
  diff       Diff export against a baseline JSONL, produce net-new JSON files
  import     Run sanity check + import net-new tasks to destination account
  finalize   Append net-new tasks to baseline JSONL, generate summary
  status     Show current delivery state

Environment Variables:
  SOURCE_API_KEY     Fleet API key for the source account (used in export phase)
  DEST_API_KEY       Fleet API key for the destination account (used in import phase)
  FLEET_API_KEY      Fallback if SOURCE/DEST keys are not set

Usage:
  # Export from source
  SOURCE_API_KEY=sk_... python3 delivery.py export --project-key proj_... -o export.json

  # Diff against baseline
  python3 delivery.py diff --export-file export.json --baseline tasks.jsonl

  # Import to destination (with sanity check)
  DEST_API_KEY=sk_... python3 delivery.py import --project-key proj_...

  # Append to baseline + generate summary
  python3 delivery.py finalize --baseline tasks.jsonl --day tue

  # Check progress
  python3 delivery.py status
"""

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, date

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Default multi-app environments (can be overridden with --multi-app-envs)
DEFAULT_MULTI_APP_ENVS = {"operations", "finance", "revops"}

TODAY = date.today().isoformat()


def get_source_api_key():
    key = os.environ.get("SOURCE_API_KEY") or os.environ.get("FLEET_API_KEY")
    if not key:
        print("Error: Set SOURCE_API_KEY or FLEET_API_KEY environment variable.")
        sys.exit(1)
    return key


def get_dest_api_key():
    key = os.environ.get("DEST_API_KEY") or os.environ.get("FLEET_API_KEY")
    if not key:
        print("Error: Set DEST_API_KEY or FLEET_API_KEY environment variable.")
        sys.exit(1)
    return key


def default_work_dir():
    return os.getcwd()


def state_path(work_dir):
    return os.path.join(work_dir, f"delivery_state_{TODAY}.json")


def load_state(work_dir):
    path = state_path(work_dir)
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {"date": TODAY, "phases_completed": []}


def save_state(state, work_dir):
    with open(state_path(work_dir), "w") as f:
        json.dump(state, f, indent=2)


# === Phase: Export ===
def phase_export(args):
    """Export all prod tasks from source account."""
    work_dir = args.work_dir or default_work_dir()
    out = args.output or os.path.join(work_dir, f"delivery_export_{TODAY}.json")

    print("=== PHASE: EXPORT ===")
    if args.project_key:
        print(f"Project: {args.project_key}")
    print(f"Output: {out}")
    print()

    if os.path.exists(out):
        size_mb = os.path.getsize(out) / (1024 * 1024)
        print(f"Export file already exists ({size_mb:.1f} MB).")
        resp = input("Re-export? [y/N]: ").strip().lower()
        if resp != "y":
            print("Using existing export file.")
            with open(out) as f:
                tasks = json.load(f)
            if isinstance(tasks, dict):
                tasks = tasks.get("tasks", [])
            print(f"Contains {len(tasks)} tasks.")
            state = load_state(work_dir)
            state["export_file"] = out
            state["export_count"] = len(tasks)
            if "export" not in state["phases_completed"]:
                state["phases_completed"].append("export")
            save_state(state, work_dir)
            return

    api_key = get_source_api_key()

    cmd = [
        sys.executable,
        os.path.join(SCRIPT_DIR, "export_tasks.py"),
        "-o", out,
    ]
    if args.project_key:
        cmd.extend(["--project-key", args.project_key])

    env = os.environ.copy()
    env["FLEET_API_KEY"] = api_key

    print("Running export...")
    print()

    result = subprocess.run(cmd, env=env, text=True)

    if result.returncode != 0:
        print(f"\nExport failed with exit code {result.returncode}")
        sys.exit(1)

    with open(out) as f:
        tasks = json.load(f)
    if isinstance(tasks, dict):
        tasks = tasks.get("tasks", [])

    size_mb = os.path.getsize(out) / (1024 * 1024)
    print(f"\nExport complete: {len(tasks)} tasks ({size_mb:.1f} MB)")

    state = load_state(work_dir)
    state["export_file"] = out
    state["export_count"] = len(tasks)
    if "export" not in state["phases_completed"]:
        state["phases_completed"].append("export")
    save_state(state, work_dir)


# === Phase: Diff ===
def phase_diff(args):
    """Diff export against baseline JSONL, produce net-new JSON files."""
    work_dir = args.work_dir or default_work_dir()
    state = load_state(work_dir)

    print("=== PHASE: DIFF ===")

    # Find export file
    export_file = args.export_file or state.get("export_file")
    if not export_file or not os.path.exists(export_file):
        print(f"Export file not found: {export_file}")
        print("Run 'export' phase first or pass --export-file.")
        sys.exit(1)

    baseline = args.baseline
    if not baseline or not os.path.exists(baseline):
        print(f"Baseline file not found: {baseline}")
        print("Pass --baseline <path-to-tasks.jsonl>")
        sys.exit(1)

    multi_app_envs = set(args.multi_app_envs) if args.multi_app_envs else DEFAULT_MULTI_APP_ENVS

    print(f"Export file: {export_file}")
    print(f"Baseline: {baseline}")
    print(f"Multi-app envs: {', '.join(sorted(multi_app_envs))}")
    print()

    # Load existing keys from baseline JSONL
    existing_keys = set()
    with open(baseline) as f:
        for line in f:
            line = line.strip()
            if line:
                task = json.loads(line)
                existing_keys.add(task["key"])

    # Load export
    with open(export_file) as f:
        exported = json.load(f)
    if isinstance(exported, dict):
        exported = exported.get("tasks", [])

    # Determine env field name
    if exported:
        sample = exported[0]
        env_field = next(
            (k for k in ["env_id", "env_key", "environment_id"] if k in sample),
            "env_id",
        )
    else:
        env_field = "env_id"

    # Find net-new
    net_new = [t for t in exported if t.get("key") not in existing_keys]
    single_app = [t for t in net_new if t.get(env_field, "") not in multi_app_envs]
    multi_app = [t for t in net_new if t.get(env_field, "") in multi_app_envs]

    single_env_counts = Counter(t.get(env_field, "unknown") for t in single_app)
    multi_env_counts = Counter(t.get(env_field, "unknown") for t in multi_app)
    missing_verifier = [t for t in net_new if not t.get("verifier_func")]

    # Print summary
    print(f"Source tasks: {len(exported)}")
    print(f"Existing in baseline: {len(existing_keys)}")
    print(f"Overlap: {len(exported) - len(net_new)}")
    print(f"Net-new total: {len(net_new)}")
    print()

    print(f"--- Single-app: {len(single_app)} tasks ---")
    for env, count in sorted(single_env_counts.items(), key=lambda x: -x[1]):
        print(f"  {env}: {count}")
    print()

    print(f"--- Multi-app: {len(multi_app)} tasks ---")
    for env, count in sorted(multi_env_counts.items(), key=lambda x: -x[1]):
        print(f"  {env}: {count}")
    print()

    if missing_verifier:
        print(f"WARNING: {len(missing_verifier)} tasks missing verifier_func!")
        for t in missing_verifier[:10]:
            print(f"  {t.get('key')} ({t.get(env_field, 'unknown')})")
        if len(missing_verifier) > 10:
            print(f"  ... and {len(missing_verifier) - 10} more")
    else:
        print(f"All {len(net_new)} net-new tasks have verifier_func.")

    env_combos = set(
        (t.get(env_field, ""), t.get("version", ""), t.get("data_id", ""), t.get("data_version", ""))
        for t in net_new
    )
    print(f"\nSanity check: {len(env_combos)} unique env combos (instances to spin up)")

    # Write output files
    single_path = os.path.join(work_dir, f"delivery_single_app_{TODAY}.json")
    multi_path = os.path.join(work_dir, f"delivery_multi_app_{TODAY}.json")
    all_path = os.path.join(work_dir, f"delivery_all_{TODAY}.json")

    if single_app:
        with open(single_path, "w") as f:
            json.dump(single_app, f, indent=2, ensure_ascii=False)
        print(f"\nWrote single-app: {single_path} ({len(single_app)} tasks)")

    if multi_app:
        with open(multi_path, "w") as f:
            json.dump(multi_app, f, indent=2, ensure_ascii=False)
        print(f"Wrote multi-app: {multi_path} ({len(multi_app)} tasks)")

    with open(all_path, "w") as f:
        json.dump(net_new, f, indent=2, ensure_ascii=False)
    print(f"Wrote combined: {all_path} ({len(net_new)} tasks)")

    # README preview
    all_single_envs = sorted(set(t.get(env_field, "") for t in single_app))
    all_multi_envs = sorted(set(t.get(env_field, "") for t in multi_app))
    print(f"\n=== README ENTRY PREVIEW ===")
    print(f"| Single-App Tasks Batch N | {len(single_app)} | {', '.join(all_single_envs)} | Delivered |")
    if multi_app:
        print(f"| Multi-App Tasks Batch N | {len(multi_app)} | {', '.join(all_multi_envs)} | Delivered |")

    # Save state
    state["diff_file_single"] = single_path if single_app else None
    state["diff_file_multi"] = multi_path if multi_app else None
    state["diff_file_all"] = all_path
    state["net_new_total"] = len(net_new)
    state["net_new_single"] = len(single_app)
    state["net_new_multi"] = len(multi_app)
    state["single_env_counts"] = dict(single_env_counts)
    state["multi_env_counts"] = dict(multi_env_counts)
    state["env_field"] = env_field
    state["baseline"] = baseline
    if "diff" not in state["phases_completed"]:
        state["phases_completed"].append("diff")
    save_state(state, work_dir)


# === Phase: Import ===
def phase_import(args):
    """Run sanity check + import on net-new tasks."""
    work_dir = args.work_dir or default_work_dir()
    state = load_state(work_dir)

    print("=== PHASE: IMPORT ===")

    if "diff" not in state.get("phases_completed", []):
        print("Run 'diff' phase first.")
        sys.exit(1)

    import_type = args.type or "all"
    if import_type == "single-app":
        import_file = state.get("diff_file_single")
        label = "single-app"
    elif import_type == "multi-app":
        import_file = state.get("diff_file_multi")
        label = "multi-app"
    else:
        import_file = state.get("diff_file_all")
        label = "all"

    if not import_file or not os.path.exists(import_file):
        print(f"No {label} diff file found. Run 'diff' phase first.")
        sys.exit(1)

    with open(import_file) as f:
        tasks = json.load(f)
    print(f"Importing {len(tasks)} {label} tasks from: {import_file}")
    print(f"Destination account: (via DEST_API_KEY)")
    print()

    resp = input(f"Proceed with sanity check + import of {len(tasks)} tasks? [y/N]: ").strip().lower()
    if resp != "y":
        print("Import cancelled.")
        return

    api_key = get_dest_api_key()

    cmd = [
        sys.executable,
        os.path.join(SCRIPT_DIR, "import_tasks.py"),
        import_file,
    ]
    if args.project_key:
        cmd.extend(["--project-key", args.project_key])

    env = os.environ.copy()
    env["FLEET_API_KEY"] = api_key

    print(f"Running import with sanity check...")
    print("=" * 60)
    print()

    result = subprocess.run(cmd, env=env, text=True)

    if result.returncode != 0:
        print(f"\nImport failed with exit code {result.returncode}")
        state["import_failed"] = True
        save_state(state, work_dir)
        sys.exit(1)

    print(f"\nImport complete!")
    state[f"imported_{label}"] = True
    if "import" not in state["phases_completed"]:
        state["phases_completed"].append("import")
    save_state(state, work_dir)


# === Phase: Finalize ===
def phase_finalize(args):
    """Append net-new tasks to baseline JSONL and generate summary."""
    work_dir = args.work_dir or default_work_dir()
    state = load_state(work_dir)

    print("=== PHASE: FINALIZE ===")

    if "import" not in state.get("phases_completed", []):
        resp = input("WARNING: Import phase not completed. Proceed anyway? [y/N]: ").strip().lower()
        if resp != "y":
            print("Finalize cancelled.")
            return

    all_file = state.get("diff_file_all")
    if not all_file or not os.path.exists(all_file):
        all_file = os.path.join(work_dir, f"delivery_all_{TODAY}.json")
    if not os.path.exists(all_file):
        print(f"Net-new file not found: {all_file}")
        sys.exit(1)

    with open(all_file) as f:
        net_new = json.load(f)

    baseline = args.baseline or state.get("baseline")
    if not baseline:
        print("Error: pass --baseline <path-to-tasks.jsonl>")
        sys.exit(1)

    env_field = state.get("env_field", "env_id")

    # Append to baseline JSONL
    print(f"\nAppending {len(net_new)} tasks to {baseline}...")
    appended = 0
    with open(baseline, "a") as f:
        for task in net_new:
            jsonl_task = {
                "key": task.get("key"),
                "prompt": task.get("prompt", ""),
                "environment_id": task.get(env_field, task.get("environment_id", "")),
                "version": task.get("version", ""),
                "data_id": task.get("data_id", ""),
                "data_version": task.get("data_version", ""),
                "env_variables": task.get("env_variables", {}),
                "metadata": task.get("metadata", {}),
                "output_json_schema": task.get("output_json_schema"),
                "verifier_func": task.get("verifier_func", ""),
            }
            f.write(json.dumps(jsonl_task, ensure_ascii=False) + "\n")
            appended += 1

    print(f"Appended {appended} tasks")

    total_lines = 0
    with open(baseline) as f:
        for _ in f:
            total_lines += 1
    print(f"Baseline now has {total_lines} tasks total")

    # Summary
    day = args.day or ("tue" if datetime.now().weekday() <= 1 else "thu")
    single_count = state.get("net_new_single", 0)
    multi_count = state.get("net_new_multi", 0)
    single_envs = sorted(state.get("single_env_counts", {}).keys())
    multi_envs = sorted(state.get("multi_env_counts", {}).keys())

    print(f"\n=== DELIVERY SUMMARY ===")
    print(f"Date: {TODAY}")
    print(f"Day: {'Tuesday (new batch)' if day == 'tue' else 'Thursday (add to batch)'}")
    if single_count > 0:
        print(f"Single-app: {single_count} tasks ({', '.join(single_envs)})")
    if multi_count > 0:
        print(f"Multi-app: {multi_count} tasks ({', '.join(multi_envs)})")
    print(f"Total delivered: {single_count + multi_count}")
    print(f"Baseline total: {total_lines}")

    state["finalized"] = True
    state["baseline_total"] = total_lines
    if "finalize" not in state["phases_completed"]:
        state["phases_completed"].append("finalize")
    save_state(state, work_dir)


# === Phase: Status ===
def phase_status(args):
    """Show current delivery state."""
    work_dir = args.work_dir or default_work_dir()
    state = load_state(work_dir)
    print(f"=== DELIVERY STATUS ({state.get('date', TODAY)}) ===")
    print(f"Phases completed: {', '.join(state.get('phases_completed', [])) or 'none'}")
    print()

    if "export" in state.get("phases_completed", []):
        print(f"Export: {state.get('export_count', '?')} tasks -> {state.get('export_file', '?')}")

    if "diff" in state.get("phases_completed", []):
        print(f"Diff: {state.get('net_new_total', '?')} net-new "
              f"({state.get('net_new_single', '?')} single-app, "
              f"{state.get('net_new_multi', '?')} multi-app)")
        sc = state.get("single_env_counts", {})
        mc = state.get("multi_env_counts", {})
        if sc:
            print(f"  Single-app: {', '.join(f'{e}({c})' for e, c in sorted(sc.items(), key=lambda x: -x[1]))}")
        if mc:
            print(f"  Multi-app: {', '.join(f'{e}({c})' for e, c in sorted(mc.items(), key=lambda x: -x[1]))}")

    if "import" in state.get("phases_completed", []):
        print("Import: complete")

    if "finalize" in state.get("phases_completed", []):
        print(f"Finalize: baseline has {state.get('baseline_total', '?')} tasks")


# === Main ===
def main():
    parser = argparse.ArgumentParser(
        description="Task Delivery Script — Phased export, diff, import workflow",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Phases (run in order):
  export      Export all prod tasks from source account
  diff        Diff export against baseline JSONL, produce net-new files
  import      Sanity check + import to destination account
  finalize    Append to baseline JSONL + generate summary
  status      Show delivery progress

Environment Variables:
  SOURCE_API_KEY   API key for source account (export phase)
  DEST_API_KEY     API key for destination account (import phase)
  FLEET_API_KEY    Fallback for both (if SOURCE/DEST not set)
        """,
    )

    parser.add_argument(
        "--work-dir", "-w",
        help="Working directory for intermediate files (default: cwd)",
    )

    subparsers = parser.add_subparsers(dest="phase", help="Delivery phase")

    # Export
    export_p = subparsers.add_parser("export", help="Export tasks from source")
    export_p.add_argument("--project-key", "-p", help="Project key to export")
    export_p.add_argument("--output", "-o", help="Output filename")

    # Diff
    diff_p = subparsers.add_parser("diff", help="Diff export against baseline")
    diff_p.add_argument("--export-file", help="Path to export JSON")
    diff_p.add_argument("--baseline", "-b", required=True, help="Path to baseline JSONL")
    diff_p.add_argument(
        "--multi-app-envs", nargs="*",
        help=f"Multi-app environment names (default: {', '.join(sorted(DEFAULT_MULTI_APP_ENVS))})",
    )

    # Import
    import_p = subparsers.add_parser("import", help="Sanity check + import")
    import_p.add_argument(
        "--type", choices=["single-app", "multi-app", "all"],
        default="all", help="Which tasks to import (default: all)",
    )
    import_p.add_argument("--project-key", "-p", help="Destination project key")

    # Finalize
    final_p = subparsers.add_parser("finalize", help="Append to baseline + summary")
    final_p.add_argument("--baseline", "-b", help="Path to baseline JSONL")
    final_p.add_argument("--day", choices=["tue", "thu"], help="Day of week")

    # Status
    subparsers.add_parser("status", help="Show delivery progress")

    args = parser.parse_args()

    if not args.phase:
        parser.print_help()
        sys.exit(1)

    phases = {
        "export": phase_export,
        "diff": phase_diff,
        "import": phase_import,
        "finalize": phase_finalize,
        "status": phase_status,
    }

    phases[args.phase](args)


if __name__ == "__main__":
    main()
