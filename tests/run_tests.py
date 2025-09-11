#!/usr/bin/env python3
"""
Simple test runner for Fleet SDK integration tests.
"""

import subprocess
import sys
import os

def main():
    """Run the test suite."""
    print("🚀 Running Fleet SDK Integration Tests")
    print("=" * 50)
    
    # Check if API key is available
    api_key = os.getenv("FLEET_API_KEY")
    if not api_key:
        print("⚠️  No FLEET_API_KEY found in environment")
        print("   Set FLEET_API_KEY environment variable or use --api-key option")
        print()
    
    # Run tests
    cmd = [
        "python", "-m", "pytest", 
        "integration/",
        "-v",
        "--tb=short",
        "--durations=10"
    ]
    
    # Add API key if available
    if api_key:
        cmd.extend(["--api-key", api_key])
    
    print(f"Command: {' '.join(cmd)}")
    print()
    
    result = subprocess.run(cmd, cwd=".")
    
    if result.returncode == 0:
        print("\n🎉 All tests passed!")
    else:
        print(f"\n❌ Tests failed with exit code {result.returncode}")
    
    return result.returncode

if __name__ == "__main__":
    sys.exit(main())
