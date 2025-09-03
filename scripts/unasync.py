#!/usr/bin/env python3
"""Run unasync to generate sync versions of async code."""

import subprocess
import sys
from pathlib import Path


def run_unasync():
    """Run unasync on the fleet/_async directory."""
    print("Running unasync to generate sync code...")

    try:
        # Run unasync
        subprocess.run(
            [sys.executable, "-m", "unasync", "fleet/_async", "fleet", "--no-cache"],
            check=True,
        )

        print("Successfully generated sync code from async sources.")
        return 0

    except subprocess.CalledProcessError as e:
        print(f"Error running unasync: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(run_unasync())
