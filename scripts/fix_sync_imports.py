#!/usr/bin/env python3
"""Fix imports in sync files after unasync runs."""

import re
from pathlib import Path

def fix_file(filepath: Path) -> bool:
    """Fix imports and sleep calls in a single file."""
    content = filepath.read_text()
    original = content
    
    # Remove asyncio import if it exists
    content = re.sub(r'^import asyncio.*\n', '', content, flags=re.MULTILINE)
    content = re.sub(r'^import asyncio as async_time.*\n', '', content, flags=re.MULTILINE)
    # Also remove indented asyncio imports (like in functions)
    content = re.sub(r'^\s+import asyncio.*\n', '', content, flags=re.MULTILINE)
    
    # Fix any remaining asyncio.sleep or async_time.sleep calls
    content = content.replace('asyncio.sleep(', 'time.sleep(')
    content = content.replace('async_time.sleep(', 'time.sleep(')
    
    # Fix absolute imports to relative imports for verifiers
    content = content.replace('from fleet.verifiers import', 'from ..verifiers import')
    
    # Fix any remaining AsyncFleetPlaywrightWrapper references in docstrings
    content = content.replace('AsyncFleetPlaywrightWrapper', 'FleetPlaywrightWrapper')
    
    if content != original:
        filepath.write_text(content)
        return True
    return False

def main():
    """Fix all sync files."""
    sync_dir = Path(__file__).parent.parent / "fleet"
    
    # Files to fix
    files_to_fix = [
        sync_dir / "instance" / "client.py",
        sync_dir / "playwright.py",
        # Add other files here as needed
    ]
    
    for filepath in files_to_fix:
        if filepath.exists():
            if fix_file(filepath):
                print(f"Fixed {filepath}")
            else:
                print(f"No changes needed for {filepath}")

if __name__ == "__main__":
    main()