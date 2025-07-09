#!/usr/bin/env python3
"""Test script demonstrating the new hierarchical environment format."""

import asyncio
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

import fleet as flt

async def test_new_format():
    print("🚀 Testing New Environment Format")
    print("=" * 50)
    
    # Set fake API key for testing
    os.environ['FLEET_API_KEY'] = 'flt_test_key'
    
    print("\n1. Environment Discovery")
    print("-" * 30)
    
    # List categories
    categories = flt.manager.list_categories()
    print(f"Available categories: {categories}")
    
    # List environments in browser category
    browser_envs = flt.manager.list_names("browser")
    print(f"Browser environments: {browser_envs}")
    
    # List versions for chrome-desktop
    versions = flt.manager.list_versions("browser", "chrome-desktop")
    print(f"Chrome desktop versions: {versions}")
    
    # List all available environments
    all_envs = flt.manager.list_environments()
    print(f"All environments: {all_envs}")
    
    print("\n2. Environment Validation")
    print("-" * 30)
    
    # Test different formats
    test_specs = [
        "browser/chrome-desktop:v1",  # Valid
        "browser/chrome-desktop:v2",  # Valid  
        "browser/chrome-desktop",     # Valid (defaults to latest)
        "browser/chrome-desktop:v99", # Invalid version
        "browser/invalid-env:v1",     # Invalid environment
        "invalid-category/chrome:v1", # Invalid category
        "invalid-format",             # Invalid format
    ]
    
    for spec in test_specs:
        supported = flt.manager.is_environment_supported(spec)
        print(f"  {spec:<30} → {'✓' if supported else '✗'}")
    
    print("\n3. Environment Creation Examples")
    print("-" * 30)
    
    try:
        # This would create an environment with explicit version
        print("Creating browser/chrome-desktop:v1...")
        # env = await flt.env.make("browser/chrome-desktop:v1")
        print("✓ Would create Chrome Desktop v1")
        
        # This would create an environment with default (latest) version
        print("Creating browser/chrome-desktop (defaults to latest)...")
        # env = await flt.env.make("browser/chrome-desktop")
        print("✓ Would create Chrome Desktop v2 (latest)")
        
        print("Creating database/postgres:v1...")
        # env = await flt.env.make("database/postgres:v1")
        print("✓ Would create PostgreSQL v1")
        
    except Exception as e:
        print(f"Error: {e}")
    
    print("\n4. Benefits of New Format")
    print("-" * 30)
    print("✓ Hierarchical organization (browser/, database/, etc.)")
    print("✓ Version separation with : delimiter")
    print("✓ Default to latest version when omitted")
    print("✓ Docker-like naming convention")
    print("✓ Easy environment discovery")
    print("✓ Clear categorization")

if __name__ == "__main__":
    asyncio.run(test_new_format()) 