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
    
    # Fix httpx transport classes
    content = content.replace('httpx.SyncHTTPTransport', 'httpx.HTTPTransport')
    
    # Fix playwright imports for sync version
    if 'playwright' in str(filepath):
        # Fix the import statement
        content = content.replace('from playwright.async_api import sync_playwright, Browser, Page', 
                                  'from playwright.sync_api import sync_playwright, Browser, Page')
        content = content.replace('from playwright.async_api import async_playwright, Browser, Page', 
                                  'from playwright.sync_api import sync_playwright, Browser, Page')
        # Replace any remaining async_playwright references
        content = content.replace('async_playwright', 'sync_playwright')
        # Fix await statements in docstrings
        content = content.replace('await browser.start()', 'browser.start()')
        content = content.replace('await browser.screenshot()', 'browser.screenshot()')
        content = content.replace('await browser.close()', 'browser.close()')
        content = content.replace('await fleet.env.make(', 'fleet.env.make(')
        # Fix error message
        content = content.replace('Call await browser.start() first', 'Call browser.start() first')
    
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
        sync_dir / "instance" / "base.py",
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