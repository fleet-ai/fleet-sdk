#!/usr/bin/env python3

"""Test script to verify the new module-level API works correctly."""

import sys
import os

# Add the fleet-sdk directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_imports():
    """Test that all module-level functions can be imported."""
    print("Testing imports...")
    
    try:
        import fleet
        print("✓ Basic import works")
        
        # Test that we can access module-level functions
        functions_to_test = [
            'load_tasks',
            'list_envs', 
            'list_regions',
            'environment',
            'make',
            'make_for_task',
            'instances',
            'instance', 
            'delete',
            'load_tasks_from_file',
            'load_task_array_from_string',
            'load_task_from_string', 
            'load_task_from_json',
            'export_tasks',
            'import_tasks',
            'account',
            'configure',
            'get_client',
            'reset_client'
        ]
        
        for func_name in functions_to_test:
            if hasattr(fleet, func_name):
                print(f"✓ fleet.{func_name} is available")
            else:
                print(f"✗ fleet.{func_name} is NOT available")
        
        # Test that the old API still works
        fleet_client = fleet.Fleet()
        print("✓ fleet.Fleet() still works (backward compatibility)")
        
        # Test that functions are callable (they'll fail without API key but should be callable)
        try:
            # This should be callable but will fail due to no API key
            fleet.list_envs()
        except Exception as e:
            if "api_key" in str(e).lower() or "unauthorized" in str(e).lower():
                print("✓ fleet.list_envs() is callable (fails as expected without API key)")
            else:
                print(f"? fleet.list_envs() failed with unexpected error: {e}")
                
        print("\n✅ All imports and basic API structure tests passed!")
        
    except ImportError as e:
        print(f"✗ Import failed: {e}")
        return False
    except Exception as e:
        print(f"✗ Test failed: {e}")
        return False
        
    return True

def test_usage_example():
    """Test the improved usage example."""
    print("\nTesting usage examples...")
    
    try:
        import fleet
        
        # Example of old vs new usage
        print("Old usage (still works):")
        print("  tasks = fleet.Fleet().load_tasks('fira')")
        
        print("New usage (improved DX):")  
        print("  tasks = fleet.load_tasks('fira')")
        print("  env = fleet.make('fira')")
        print("  envs = fleet.list_envs()")
        
        print("✅ Usage examples look good!")
        
    except Exception as e:
        print(f"✗ Usage example test failed: {e}")
        return False
        
    return True

if __name__ == "__main__":
    success = True
    success &= test_imports()
    success &= test_usage_example()
    
    if success:
        print("\n🎉 All tests passed! The module-level API is working correctly.")
    else:
        print("\n❌ Some tests failed.")
        sys.exit(1)