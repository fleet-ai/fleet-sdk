#!/usr/bin/env python3
"""Script to run a bundled verifier zip file.

This script:
1. Extracts the bundle zip file
2. Creates a virtual environment
3. Installs the requirements
4. Imports and runs the verifier function
"""

import argparse
import base64
import io
import json
import os
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, Optional


def setup_virtualenv(work_dir: Path) -> Path:
    """Create and return path to a virtual environment."""
    venv_dir = work_dir / "venv"
    
    print(f"Creating virtual environment at {venv_dir}...")
    subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)
    
    # Get the python executable in the venv
    if sys.platform == "win32":
        python_exe = venv_dir / "Scripts" / "python.exe"
        pip_exe = venv_dir / "Scripts" / "pip.exe"
    else:
        python_exe = venv_dir / "bin" / "python"
        pip_exe = venv_dir / "bin" / "pip"
    
    return python_exe, pip_exe


def install_requirements(pip_exe: Path, requirements_file: Path) -> None:
    """Install requirements using pip."""
    print(f"Installing requirements from {requirements_file}...")
    subprocess.run(
        [str(pip_exe), "install", "-r", str(requirements_file)],
        check=True
    )


def run_verifier(python_exe: Path, bundle_dir: Path, verifier_args: Dict[str, Any]) -> Any:
    """Run the verifier function and return the result."""
    
    # Create a runner script that will execute in the virtual environment
    runner_script = bundle_dir / "_runner.py"
    
    runner_code = f"""
import sys
import json
from pathlib import Path

# Add bundle directory to Python path
sys.path.insert(0, str(Path(__file__).parent))

# Mock the fleet module and its components
class MockAsyncEnvironment:
    def __init__(self):
        self.data = {{}}

# Create a mock verifier decorator that just returns the function
def mock_verifier(name=None, extra_requirements=None):
    def decorator(func):
        func._is_verifier = True
        return func
    return decorator

# Set up mock fleet module
sys.modules['fleet'] = type(sys)('fleet')
sys.modules['fleet'].AsyncEnvironment = MockAsyncEnvironment
sys.modules['fleet._async'] = type(sys)('fleet._async')
sys.modules['fleet._async.verifiers'] = type(sys)('fleet._async.verifiers')
sys.modules['fleet._async.verifiers'].verifier = mock_verifier

# Now import the verifier module
import verifier

# Find the verifier function
verifier_func = None
for attr_name in dir(verifier):
    attr = getattr(verifier, attr_name)
    if callable(attr) and (hasattr(attr, '_is_verifier') or attr_name.endswith('_verifier')):
        verifier_func = attr
        break

if not verifier_func:
    print("ERROR: Could not find verifier function in module", file=sys.stderr)
    sys.exit(1)

# Create environment
env = MockAsyncEnvironment()

# Run the verifier with provided arguments
args = json.loads('{json.dumps(verifier_args)}')
result = verifier_func(env, **args)

# Output the result as JSON
print(json.dumps({{"result": result}}))
"""
    
    runner_script.write_text(runner_code)
    
    # Execute the runner script
    print("Running verifier function...")
    result = subprocess.run(
        [str(python_exe), str(runner_script)],
        capture_output=True,
        text=True,
        cwd=str(bundle_dir)
    )
    
    if result.returncode != 0:
        print(f"Error running verifier: {result.stderr}")
        raise RuntimeError(f"Verifier execution failed: {result.stderr}")
    
    # Parse the result
    try:
        output = json.loads(result.stdout)
        return output["result"]
    except json.JSONDecodeError:
        print(f"Raw output: {result.stdout}")
        raise RuntimeError("Failed to parse verifier output")


def run_bundle_from_file(bundle_path: Path, verifier_args: Optional[Dict[str, Any]] = None) -> Any:
    """Run a bundled verifier from a zip file."""
    if verifier_args is None:
        verifier_args = {}
    
    with open(bundle_path, 'rb') as f:
        bundle_data = f.read()
    
    return run_bundle_from_bytes(bundle_data, verifier_args)


def run_bundle_from_base64(bundle_b64: str, verifier_args: Optional[Dict[str, Any]] = None) -> Any:
    """Run a bundled verifier from base64-encoded data."""
    if verifier_args is None:
        verifier_args = {}
    
    bundle_data = base64.b64decode(bundle_b64)
    return run_bundle_from_bytes(bundle_data, verifier_args)


def run_bundle_from_bytes(bundle_data: bytes, verifier_args: Optional[Dict[str, Any]] = None) -> Any:
    """Run a bundled verifier from raw bytes."""
    if verifier_args is None:
        verifier_args = {}
    
    with tempfile.TemporaryDirectory() as temp_dir:
        work_dir = Path(temp_dir)
        bundle_dir = work_dir / "bundle"
        bundle_dir.mkdir()
        
        # Extract the bundle
        print(f"Extracting bundle to {bundle_dir}...")
        with zipfile.ZipFile(io.BytesIO(bundle_data), 'r') as zf:
            zf.extractall(bundle_dir)
        
        # List extracted files
        print("\nExtracted files:")
        for file_path in bundle_dir.rglob("*"):
            if file_path.is_file():
                print(f"  - {file_path.relative_to(bundle_dir)}")
        
        # Check for requirements.txt
        requirements_file = bundle_dir / "requirements.txt"
        if not requirements_file.exists():
            print("Warning: No requirements.txt found in bundle")
            requirements_file = None
        
        # Create virtual environment and install requirements
        python_exe, pip_exe = setup_virtualenv(work_dir)
        
        if requirements_file:
            install_requirements(pip_exe, requirements_file)
        
        # Run the verifier
        result = run_verifier(python_exe, bundle_dir, verifier_args)
        
        print(f"\nVerifier result: {result}")
        return result


def main():
    parser = argparse.ArgumentParser(description="Run a bundled verifier")
    parser.add_argument("bundle", help="Path to bundle zip file or '-' for base64 from stdin")
    parser.add_argument("--args", type=json.loads, default={}, 
                       help="JSON string of arguments to pass to verifier")
    parser.add_argument("--save-bundle", help="Save the bundle to this file (useful with stdin)")
    
    args = parser.parse_args()
    
    try:
        if args.bundle == "-":
            # Read base64 from stdin
            print("Reading base64 bundle from stdin...")
            bundle_b64 = sys.stdin.read().strip()
            
            # Optionally save the bundle
            if args.save_bundle:
                bundle_data = base64.b64decode(bundle_b64)
                with open(args.save_bundle, 'wb') as f:
                    f.write(bundle_data)
                print(f"Saved bundle to {args.save_bundle}")
            
            result = run_bundle_from_base64(bundle_b64, args.args)
        else:
            # Read from file
            bundle_path = Path(args.bundle)
            if not bundle_path.exists():
                print(f"Error: Bundle file not found: {bundle_path}")
                sys.exit(1)
            
            result = run_bundle_from_file(bundle_path, args.args)
        
        print(f"\nFinal result: {result}")
        
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main() 