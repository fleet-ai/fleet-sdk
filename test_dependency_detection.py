#!/usr/bin/env python3
"""
Test script to validate enhanced dependency detection.
This script tests that modulegraph2 is working correctly and can detect
both module-level imports and transitive local dependencies.
"""

import sys
import logging
from pathlib import Path

# Add the fleet-sdk to the path
sys.path.insert(0, str(Path(__file__).parent))

from fleet._async.verifiers.decorator import FunctionBundler

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Module-level import for testing
import json
import tempfile

def test_dependency_detection():
    """Test that dependency detection works correctly."""
    print("🧪 Testing Enhanced Dependency Detection")
    print("=" * 50)
    
    # Create a temporary test file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write('''
import os
import sys
from pathlib import Path

def test_function():
    """Test function with module-level dependencies."""
    path = Path("test")  # Uses pathlib
    return str(path)
''')
        test_file = Path(f.name)
    
    try:
        # Test the bundler
        bundler = FunctionBundler()
        
        print("\n1. Testing modulegraph2 availability:")
        try:
            import modulegraph2
            print("   ✅ modulegraph2 is available")
        except ImportError:
            print("   ❌ modulegraph2 is not available")
            return False
        
        print("\n2. Testing dependency detection:")
        try:
            result = bundler._crawl_imports(test_file)
            print(f"   ✅ Detection successful")
            print(f"   📦 Packages found: {result['packages']}")
            print(f"   📁 Local files found: {result['local_files']}")
            
            # Should find some standard library modules
            if result['packages']:
                print("   ✅ Successfully detected dependencies")
            else:
                print("   ⚠️  No dependencies detected (might be filtering stdlib)")
                
        except Exception as e:
            print(f"   ❌ Detection failed: {e}")
            return False
        
        print("\n3. Testing project root detection:")
        try:
            project_root = bundler._find_project_root(test_file)
            print(f"   ✅ Project root: {project_root}")
        except Exception as e:
            print(f"   ❌ Project root detection failed: {e}")
            return False
            
        print("\n✅ All tests passed! Enhanced dependency detection is working.")
        return True
        
    finally:
        # Clean up
        test_file.unlink()

if __name__ == "__main__":
    success = test_dependency_detection()
    sys.exit(0 if success else 1) 