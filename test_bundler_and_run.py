#!/usr/bin/env python3
"""Test bundler functionality and demonstrate running the bundle."""

import asyncio
import base64
import subprocess
import sys
import zipfile
import io
from pathlib import Path
from fleet import AsyncEnvironment
from fleet._async.verifiers import verifier
from fleet._async.verifiers.bundler import FunctionBundler
from zuba import helper_function_four


def helper_function(x: int, y: int) -> int:
    """Helper function that will be bundled."""
    return x + y


@verifier(name="test_bundler", extra_requirements=["numpy>=1.20.0"])
def test_verifier(env: AsyncEnvironment, threshold: int = 10) -> float:
    """Test verifier that uses a helper function."""
    result = helper_function(5, 7)
    result2 = helper_function_four(5, 7)
    return 1.0 if result > threshold else 0.0


def main():
    print("Testing bundler functionality...\n")
    
    # Create bundler instance
    bundler = FunctionBundler()
    
    # Create bundle
    print("Creating bundle for test_verifier...")
    bundle_data = bundler.create_bundle(
        test_verifier.func,  # The wrapped function
        extra_requirements=["numpy>=1.20.0"],
        verifier_id="test-verifier-123"
    )
    
    print("Bundle created successfully!")
    print(f"Bundle size: {len(bundle_data)} bytes")
    
    # Save bundle to file
    bundle_path = Path("test_bundle.zip")
    with open(bundle_path, "wb") as f:
        f.write(bundle_data)
    print(f"\nSaved bundle to: {bundle_path}")
    
    # Also save as base64
    bundle_b64 = base64.b64encode(bundle_data).decode('utf-8')
    b64_path = Path("test_bundle.b64")
    with open(b64_path, "w") as f:
        f.write(bundle_b64)
    print(f"Saved base64 to: {b64_path}")
    
    # Test running the bundle if runner exists
    runner_path = Path("run_bundle.py")
    if runner_path.exists():
        print("\n" + "="*60)
        print("Testing bundle execution...")
        print("="*60)
        
        # Test 1: Run with default arguments (threshold=10)
        print("\nTest 1: Running with default arguments (threshold=10)")
        try:
            result = subprocess.run(
                [sys.executable, "run_bundle.py", str(bundle_path)],
                capture_output=True,
                text=True
            )
            print("STDOUT:", result.stdout)
            if result.stderr:
                print("STDERR:", result.stderr)
        except Exception as e:
            print(f"Error: {e}")
        
        # Test 2: Run with custom arguments (threshold=15)
        print("\n" + "-"*60)
        print("Test 2: Running with custom arguments (threshold=15)")
        try:
            result = subprocess.run(
                [sys.executable, "run_bundle.py", str(bundle_path), 
                 "--args", '{"threshold": 15}'],
                capture_output=True,
                text=True
            )
            print("STDOUT:", result.stdout)
            if result.stderr:
                print("STDERR:", result.stderr)
        except Exception as e:
            print(f"Error: {e}")
        
        # Test 3: Run from base64 via stdin
        print("\n" + "-"*60)
        print("Test 3: Running from base64 via stdin")
        try:
            with open(b64_path, "r") as f:
                b64_content = f.read()
            
            result = subprocess.run(
                [sys.executable, "run_bundle.py", "-", 
                 "--save-bundle", "test_bundle_from_b64.zip"],
                input=b64_content,
                capture_output=True,
                text=True
            )
            print("STDOUT:", result.stdout)
            if result.stderr:
                print("STDERR:", result.stderr)
        except Exception as e:
            print(f"Error: {e}")
    else:
        print(f"\nRunner script not found at {runner_path}")
        print("Create run_bundle.py to test bundle execution")
    
    # Cleanup
    print("\n" + "="*60)
    print("Cleanup: You can remove these test files:")
    print(f"  - {bundle_path}")
    print(f"  - {b64_path}")
    if Path("test_bundle_from_b64.zip").exists():
        print("  - test_bundle_from_b64.zip")


if __name__ == "__main__":
    main() 