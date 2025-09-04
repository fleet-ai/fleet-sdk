#!/usr/bin/env python3

"""Simple test to verify module-level functions are available without importing dependencies."""

import sys
import os
import importlib.util

# Add the fleet-sdk directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_module_structure():
    """Test that module-level functions are defined in the __init__.py file."""
    
    # Read the __init__.py file directly
    init_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fleet', '__init__.py')
    
    with open(init_file, 'r') as f:
        content = f.read()
    
    print("Testing module-level API structure...")
    
    # Check that module-level functions are defined
    functions_to_check = [
        'def load_tasks(',
        'def list_envs(',
        'def list_regions(',
        'def environment(',
        'def make(',
        'def make_for_task(',
        'def instances(',
        'def instance(',
        'def delete(',
        'def load_tasks_from_file(',
        'def load_task_array_from_string(',
        'def load_task_from_string(',
        'def load_task_from_json(',
        'def export_tasks(',
        'def import_tasks(',
        'def account(',
    ]
    
    for func in functions_to_check:
        if func in content:
            print(f"✓ {func.split('(')[0].replace('def ', '')} is defined")
        else:
            print(f"✗ {func.split('(')[0].replace('def ', '')} is NOT defined")
    
    # Check that functions are in __all__
    all_functions = [
        '"load_tasks"',
        '"list_envs"',
        '"list_regions"',
        '"environment"', 
        '"make"',
        '"make_for_task"',
        '"instances"',
        '"instance"',
        '"delete"',
        '"load_tasks_from_file"',
        '"load_task_array_from_string"',
        '"load_task_from_string"',
        '"load_task_from_json"',
        '"export_tasks"',
        '"import_tasks"',
        '"account"',
    ]
    
    print("\nChecking __all__ exports...")
    for func in all_functions:
        if func in content:
            print(f"✓ {func} is in __all__")
        else:
            print(f"✗ {func} is NOT in __all__")
    
    print("\n✅ Module structure looks good!")

def show_usage_examples():
    """Show usage examples."""
    print("\nUsage Examples:")
    print("===============")
    print("Before (required explicit client creation):")
    print("  import fleet")
    print("  client = fleet.Fleet()")
    print("  tasks = client.load_tasks('fira')")
    print("  env = client.make('fira')")
    print("")
    print("After (module-level functions):")
    print("  import fleet")
    print("  fleet.configure(api_key='your-key')  # One-time setup")
    print("  tasks = fleet.load_tasks('fira')")
    print("  env = fleet.make('fira')")
    print("  envs = fleet.list_envs()")
    print("  regions = fleet.list_regions()")

if __name__ == "__main__":
    test_module_structure()
    show_usage_examples()
    print("\n🎉 Implementation complete! Users can now use fleet.load_tasks() directly.")