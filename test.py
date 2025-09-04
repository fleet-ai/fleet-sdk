#!/usr/bin/env python3
"""
Tool Log Analyzer

This script reads tool_log data and analyzes the different types of tool actions present.
It can read from either a JSON file or the SQLite database directly.
"""

import json
import sqlite3
from collections import defaultdict, Counter
from typing import Dict, List, Any
import sys
import argparse


def analyze_tool_logs_from_json(filepath: str) -> None:
    """Analyze tool logs from a JSON file."""
    print(f"Reading tool logs from: {filepath}\n")
    
    with open(filepath, 'r') as f:
        data = json.load(f)
    
    # Handle different JSON structures
    if isinstance(data, dict):
        if 'rows' in data:
            # SQLite query result format
            columns = data.get('columns', [])
            rows = data.get('rows', [])
            
            # Find column indices
            tool_name_idx = columns.index('tool_name') if 'tool_name' in columns else 2
            action_idx = columns.index('action') if 'action' in columns else 3
            
            entries = []
            for row in rows:
                entries.append({
                    'tool_name': row[tool_name_idx],
                    'action': row[action_idx],
                    'parameters': json.loads(row[4]) if row[4] else {},
                    'success': row[6] if len(row) > 6 else True
                })
        elif 'tool_logs' in data:
            # Snapshot format
            entries = data['tool_logs']
        else:
            # Direct list of entries
            entries = data if isinstance(data, list) else []
    else:
        entries = data if isinstance(data, list) else []
    
    analyze_entries(entries)


def analyze_tool_logs_from_db(db_path: str) -> None:
    """Analyze tool logs directly from SQLite database."""
    print(f"Reading tool logs from database: {db_path}\n")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Get all tool logs
    cursor.execute("""
        SELECT tool_name, action, parameters, success, error, duration_ms, session_id
        FROM tool_log
        ORDER BY timestamp
    """)
    
    entries = []
    for row in cursor.fetchall():
        entries.append({
            'tool_name': row[0],
            'action': row[1],
            'parameters': json.loads(row[2]) if row[2] else {},
            'success': bool(row[3]),
            'error': row[4],
            'duration_ms': row[5],
            'session_id': row[6]
        })
    
    conn.close()
    analyze_entries(entries)


def analyze_entries(entries: List[Dict[str, Any]]) -> None:
    """Analyze a list of tool log entries."""
    if not entries:
        print("No tool log entries found!")
        return
    
    # Group by tool_name and action
    tool_actions = defaultdict(lambda: defaultdict(list))
    tool_counts = Counter()
    action_counts = Counter()
    success_counts = defaultdict(lambda: {'success': 0, 'failure': 0})
    
    for entry in entries:
        tool_name = entry.get('tool_name', 'unknown')
        action = entry.get('action', 'unknown')
        success = entry.get('success', True)
        
        tool_actions[tool_name][action].append(entry)
        tool_counts[tool_name] += 1
        action_counts[f"{tool_name}.{action}"] += 1
        
        if success:
            success_counts[tool_name]['success'] += 1
        else:
            success_counts[tool_name]['failure'] += 1
    
    # Print summary
    print(f"=== TOOL LOG SUMMARY ===")
    print(f"Total entries: {len(entries)}")
    print(f"Unique tools: {len(tool_actions)}")
    print(f"Unique actions: {len(action_counts)}")
    print()
    
    # Print tool breakdown
    print("=== TOOLS OVERVIEW ===")
    for tool_name, count in tool_counts.most_common():
        success = success_counts[tool_name]['success']
        failure = success_counts[tool_name]['failure']
        success_rate = (success / count) * 100 if count > 0 else 0
        
        print(f"\n{tool_name}: {count} total")
        print(f"  Success: {success} ({success_rate:.1f}%)")
        if failure > 0:
            print(f"  Failure: {failure} ({(failure/count)*100:.1f}%)")
        
        # Show actions for this tool
        print(f"  Actions:")
        for action, action_entries in sorted(tool_actions[tool_name].items()):
            print(f"    - {action}: {len(action_entries)}")
            
            # Show sample parameters for interesting actions
            if action in ['outgoing_Network.enable', 'left_click', 'type', 'navigate']:
                sample = action_entries[0]
                if sample.get('parameters'):
                    print(f"      Sample params: {json.dumps(sample['parameters'], indent=8)[:100]}...")
    
    # Print top actions
    print("\n=== TOP 10 ACTIONS ===")
    for action_full, count in action_counts.most_common(10):
        print(f"{action_full}: {count}")
    
    # Analyze CDP messages specifically
    cdp_entries = [e for e in entries if e.get('tool_name') == 'cdp']
    if cdp_entries:
        print("\n=== CDP MESSAGE ANALYSIS ===")
        cdp_methods = Counter()
        cdp_directions = Counter()
        
        for entry in cdp_entries:
            params = entry.get('parameters', {})
            if isinstance(params, str):
                params = json.loads(params)
            
            direction = params.get('direction', 'unknown')
            method = params.get('method', 'unknown')
            
            cdp_directions[direction] += 1
            if method != 'unknown':
                cdp_methods[method] += 1
        
        print(f"Total CDP messages: {len(cdp_entries)}")
        print(f"Directions: {dict(cdp_directions)}")
        print(f"\nTop CDP methods:")
        for method, count in cdp_methods.most_common(10):
            print(f"  {method}: {count}")
    
    # Analyze browser actions
    browser_entries = [e for e in entries if e.get('tool_name') == 'browser']
    if browser_entries:
        print("\n=== BROWSER ACTIONS ===")
        browser_action_counts = Counter()
        
        for entry in browser_entries:
            action = entry.get('action', 'unknown')
            browser_action_counts[action] += 1
        
        print(f"Total browser actions: {len(browser_entries)}")
        for action, count in browser_action_counts.most_common():
            print(f"  {action}: {count}")


def main():
    parser = argparse.ArgumentParser(description='Analyze tool logs')
    parser.add_argument('filepath', help='Path to JSON file or SQLite database')
    parser.add_argument('--db', action='store_true', help='Read from SQLite database instead of JSON')
    
    args = parser.parse_args()
    
    try:
        if args.db or args.filepath.endswith('.sqlite') or args.filepath.endswith('.db'):
            analyze_tool_logs_from_db(args.filepath)
        else:
            analyze_tool_logs_from_json(args.filepath)
    except FileNotFoundError:
        print(f"Error: File not found: {args.filepath}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in file: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()