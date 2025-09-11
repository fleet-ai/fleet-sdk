#!/usr/bin/env python3
"""
Unit test runner for Fleet SDK.
Runs unit tests with mock data - no API calls required.
"""

import sys
import os
import subprocess
from pathlib import Path

def main():
    """Run unit tests."""
    # Get the directory containing this script
    script_dir = Path(__file__).parent
    project_root = script_dir.parent.parent
    
    # Add project root to Python path
    sys.path.insert(0, str(project_root))
    
    # Change to unit test directory
    os.chdir(script_dir)
    
    # Run pytest with unit test configuration
    cmd = [
        sys.executable, "-m", "pytest",
        "-v",
        "--tb=short",
        "--strict-markers",
        "--disable-warnings",
        "--timeout=30",
        "."
    ]
    
    print("🧪 Running Fleet SDK Unit Tests")
    print("=" * 50)
    print(f"Command: {' '.join(cmd)}")
    print("=" * 50)
    
    try:
        result = subprocess.run(cmd, check=False)
        return result.returncode
    except KeyboardInterrupt:
        print("\n⚠️  Tests interrupted by user")
        return 1
    except Exception as e:
        print(f"❌ Error running tests: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
