#!/usr/bin/env python3
"""Simple script to run a bundled function without decorator handling."""

import argparse
import io
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, Optional


def run_bundle(bundle_path: Path, args: Dict[str, Any] = None) -> Any:
    """Run a bundled function from a zip file."""
    if args is None:
        args = {}
    
    with tempfile.TemporaryDirectory() as temp_dir:
        work_dir = Path(temp_dir)
        
        # Extract the bundle
        print(f"Extracting bundle...")
        with zipfile.ZipFile(bundle_path, 'r') as zf:
            zf.extractall(work_dir)
        
        # Create runner script
        runner_script = work_dir / "_runner.py"
        runner_code = f"""
import sys
import json
from pathlib import Path

# Add bundle directory to Python path
sys.path.insert(0, str(Path(__file__).parent))

# Import the verifier module
import verifier

# Find the main function (usually ends with _verifier or simple_verifier)
func = None
for attr_name in dir(verifier):
    attr = getattr(verifier, attr_name)
    if callable(attr) and not attr_name.startswith('_') and attr_name.endswith('verifier'):
        func = attr
        break

if not func:
    print("ERROR: Could not find function in module", file=sys.stderr)
    sys.exit(1)

# Mock environment
class MockEnv:
    pass

env = MockEnv()

# Run the function
args = {json.dumps(args)}
result = func(env, **args)

# Output result
print(json.dumps({{"result": result}}))
"""
        
        runner_script.write_text(runner_code)
        
        # Run the script
        print("Running function...")
        result = subprocess.run(
            [sys.executable, str(runner_script)],
            capture_output=True,
            text=True,
            cwd=str(work_dir)
        )
        
        if result.returncode != 0:
            print(f"Error: {result.stderr}")
            return None
        
        # Parse result
        try:
            output = json.loads(result.stdout)
            return output["result"]
        except json.JSONDecodeError:
            print(f"Raw output: {result.stdout}")
            return None


def main():
    parser = argparse.ArgumentParser(description="Run a bundled function")
    parser.add_argument("bundle", help="Path to bundle zip file")
    parser.add_argument("--args", type=json.loads, default={}, 
                       help="JSON string of arguments")
    
    args = parser.parse_args()
    
    bundle_path = Path(args.bundle)
    if not bundle_path.exists():
        print(f"Error: Bundle file not found: {bundle_path}")
        sys.exit(1)
    
    result = run_bundle(bundle_path, args.args)
    print(f"\nResult: {result}")


if __name__ == "__main__":
    main() 