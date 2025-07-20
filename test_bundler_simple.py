#!/usr/bin/env python3
"""Simple test of bundler functionality without decorators."""

import base64
import subprocess
import sys
from pathlib import Path
from fleet._async.verifiers.bundler import FunctionBundler


def simple_verifier(env, threshold=10):
    """Simple verifier without decorator.
    
    This demonstrates that we can bundle and run functions
    without the @verifier decorator.
    """
    # Import helper functions inside the function
    # This ensures the import is captured by inspect.getsource()
    from zuba import helper_function_four
    
    def helper_function(x, y):
        """Helper function that will be bundled."""
        return x + y
    
    result = helper_function(5, 7)
    result2 = helper_function_four(5, 7)
    return 1.0 if result > threshold else 0.0


def main():
    print("Testing bundler with simple function...\n")
    
    # Create bundler instance
    bundler = FunctionBundler()
    
    # Create bundle
    print("Creating bundle for simple_verifier...")
    bundle_data = bundler.create_bundle(
        simple_verifier,
        extra_requirements=["numpy>=1.20.0"],
        verifier_id="simple-verifier-123"
    )
    
    print("Bundle created successfully!")
    print(f"Bundle size: {len(bundle_data)} bytes")
    
    # Save bundle to file
    bundle_path = Path("simple_bundle.zip")
    with open(bundle_path, "wb") as f:
        f.write(bundle_data)
    print(f"\nSaved bundle to: {bundle_path}")
    
    # Test running the bundle
    runner_path = Path("run_bundle_simple.py")
    if runner_path.exists():
        print("\n" + "="*60)
        print("Testing bundle execution...")
        print("="*60)
        
        # Run with default arguments
        print("\nRunning with default arguments (threshold=10)")
        try:
            result = subprocess.run(
                [sys.executable, str(runner_path), str(bundle_path)],
                capture_output=True,
                text=True
            )
            print("STDOUT:", result.stdout)
            if result.stderr:
                print("STDERR:", result.stderr)
        except Exception as e:
            print(f"Error: {e}")
    else:
        print(f"\nCreate {runner_path} to test execution")


if __name__ == "__main__":
    main() 