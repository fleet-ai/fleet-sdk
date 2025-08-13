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
    
    # Fix imports based on file location
    # Since async code now imports from sync models/config, we need to fix the generated sync imports
    rel_path = filepath.relative_to(Path(__file__).parent.parent / "fleet")
    
    # Fix imports for files in different subdirectories
    if "fleet/instance" in str(filepath):
        # Files in fleet/instance/ should use .. for fleet level imports
        content = content.replace('from ...config import', 'from ..config import')
        content = content.replace('from ...instance.models import', 'from .models import')
    elif "fleet/env" in str(filepath):
        # Files in fleet/env/ should use .. for fleet level imports
        content = content.replace('from ...models import', 'from ..models import')
    elif "fleet/resources" in str(filepath):
        # Files in fleet/resources/ should use .. for fleet level imports
        content = content.replace('from ...instance.models import', 'from ..instance.models import')
    
    # Fix imports in top-level fleet files
    if rel_path.parts[0] in ['base.py', 'client.py'] and len(rel_path.parts) == 1:
        # Top-level files should use . for fleet level imports
        content = content.replace('from ..models import', 'from .models import')
        content = content.replace('from ..config import', 'from .config import')
    
    # Fix __init__.py imports - the class is called SyncEnv, not Environment
    if rel_path.parts[0] == '__init__.py' and len(rel_path.parts) == 1:
        content = content.replace('from .client import Fleet, Environment', 'from .client import Fleet, SyncEnv')
        content = content.replace('"Environment",', '"SyncEnv",')
        content = content.replace("'Environment',", "'SyncEnv',")
    
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
    
    # Process all Python files in the fleet directory (excluding _async)
    fixed_count = 0
    for filepath in sync_dir.rglob("*.py"):
        if "_async" not in str(filepath):
            if fix_file(filepath):
                print(f"Fixed {filepath}")
                fixed_count += 1
    
    if fixed_count == 0:
        print("No files needed fixing")

if __name__ == "__main__":
    main()