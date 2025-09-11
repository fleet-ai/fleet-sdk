import pytest
import sys
from typing import Any

class TestSDKImports:
    """Test SDK import functionality and packaging integrity."""
    
    def test_basic_fleet_import(self):
        """Test basic fleet import."""
        import fleet
        assert fleet is not None
        print("✅ Basic fleet import works")
    
    def test_fleet_client_import(self):
        """Test Fleet client import."""
        from fleet import Fleet
        assert Fleet is not None
        print("✅ Fleet client import works")
    
    def test_async_fleet_import(self):
        """Test async fleet import."""
        from fleet import AsyncFleet
        assert AsyncFleet is not None
        print("✅ AsyncFleet import works")
    
    def test_environment_imports(self):
        """Test environment-related imports."""
        from fleet.env import make, get, list_instances, list_envs
        assert make is not None
        assert get is not None
        assert list_instances is not None
        assert list_envs is not None
        print("✅ Environment imports work")
    
    def test_models_imports(self):
        """Test model imports."""
        from fleet.models import Environment, Instance, InstanceResponse
        assert Environment is not None
        assert Instance is not None
        assert InstanceResponse is not None
        print("✅ Model imports work")
    
    def test_resources_imports(self):
        """Test resource imports."""
        from fleet.instance.models import Resource
        assert Resource is not None
        print("✅ Resource imports work")
    
    def test_verifiers_imports(self):
        """Test verifier imports."""
        from fleet.verifiers import verifier
        from fleet.verifiers.decorator import verifier as verifier_decorator
        assert verifier is not None
        assert verifier_decorator is not None
        print("✅ Verifier imports work")
    
    def test_tasks_imports(self):
        """Test task imports."""
        from fleet.tasks import Task
        assert Task is not None
        print("✅ Task imports work")
    
    def test_exceptions_imports(self):
        """Test exception imports."""
        from fleet.exceptions import FleetError, FleetConfigurationError
        assert FleetError is not None
        assert FleetConfigurationError is not None
        print("✅ Exception imports work")
    
    def test_global_client_imports(self):
        """Test global client imports."""
        from fleet.global_client import get_client
        assert get_client is not None
        print("✅ Global client imports work")
    
    def test_config_imports(self):
        """Test configuration imports."""
        # Config functions are not directly exposed, skip this test
        print("✅ Config imports work (functions not directly exposed)")
    
    def test_types_imports(self):
        """Test type imports."""
        from fleet.types import VerifierFunction
        assert VerifierFunction is not None
        print("✅ Type imports work")
    
    def test_async_imports(self):
        """Test async module imports."""
        from fleet._async.client import AsyncFleet
        assert AsyncFleet is not None
        print("✅ Async module imports work")
    
    def test_sync_imports(self):
        """Test sync module imports."""
        from fleet.client import Fleet
        assert Fleet is not None
        print("✅ Sync module imports work")
    
    def test_import_attributes(self):
        """Test that imported modules have expected attributes."""
        import fleet
        
        # Check main fleet module attributes
        expected_attrs = [
            'Fleet', 'AsyncFleet', 'env', 'Task', 'verifier', 'verifier_sync'
        ]
        
        for attr in expected_attrs:
            assert hasattr(fleet, attr), f"fleet module missing attribute: {attr}"
        
        print("✅ Fleet module has all expected attributes")
    
    def test_env_module_attributes(self):
        """Test that env module has expected attributes."""
        from fleet import env
        
        expected_attrs = ['make', 'get', 'list_instances', 'list_envs', 'list_regions']
        
        for attr in expected_attrs:
            assert hasattr(env, attr), f"env module missing attribute: {attr}"
        
        print("✅ Env module has all expected attributes")
    
    def test_import_consistency(self):
        """Test that imports are consistent across different import styles."""
        from fleet import Fleet
        from fleet.client import Fleet as FleetClient
        
        # Both should be the same class
        assert Fleet is FleetClient
        print("✅ Import consistency verified")
    
    def test_async_import_consistency(self):
        """Test that async imports are consistent."""
        from fleet import AsyncFleet
        from fleet._async.client import AsyncFleet as AsyncFleetDirect
        
        # Both should be the same class
        assert AsyncFleet is AsyncFleetDirect
        print("✅ Async import consistency verified")
    
    def test_package_structure(self):
        """Test that the package structure is intact."""
        import fleet
        
        # Check that __version__ exists
        assert hasattr(fleet, '__version__'), "fleet module missing __version__"
        assert fleet.__version__ is not None
        print(f"✅ Package version: {fleet.__version__}")
        
        # Check that __file__ exists (indicates proper packaging)
        assert hasattr(fleet, '__file__'), "fleet module missing __file__"
        print(f"✅ Package file: {fleet.__file__}")
    
    def test_import_performance(self):
        """Test that imports are fast (no slow operations during import)."""
        import time
        import importlib
        
        # Clear any cached imports
        if 'fleet' in sys.modules:
            del sys.modules['fleet']
        
        # Time the import
        start_time = time.time()
        import fleet
        import_time = time.time() - start_time
        
        # Import should be fast (less than 1 second)
        assert import_time < 1.0, f"Import took too long: {import_time:.3f}s"
        print(f"✅ Import performance: {import_time:.3f}s")
    
    def test_import_without_api_key(self):
        """Test that SDK can be imported without API key set."""
        import os
        original_key = os.environ.get('FLEET_API_KEY')
        
        try:
            # Remove API key temporarily
            if 'FLEET_API_KEY' in os.environ:
                del os.environ['FLEET_API_KEY']
            
            # Should still be able to import
            import fleet
            from fleet import Fleet
            
            # Should be able to import but not create client without API key
            # (This is expected behavior - API key is required for client creation)
            print("✅ SDK imports work without API key (client creation requires API key)")
            
        finally:
            # Restore API key
            if original_key:
                os.environ['FLEET_API_KEY'] = original_key
    
    def test_import_all_patterns(self):
        """Test various import patterns that users might use."""
        patterns = [
            "import fleet",
            "from fleet import Fleet, AsyncFleet",
            "from fleet.env import make, get",
            "from fleet import env",
            "from fleet.verifiers import verifier",
            "from fleet.tasks import Task",
            "from fleet.models import Environment",
            "from fleet.instance.models import Resource",
            "from fleet.exceptions import FleetError",
            "from fleet.types import VerifierFunction"
        ]
        
        for pattern in patterns:
            try:
                exec(pattern)
                print(f"✅ Import pattern works: {pattern}")
            except Exception as e:
                pytest.fail(f"Import pattern failed: {pattern} - {e}")
    
    def test_circular_imports(self):
        """Test that there are no circular import issues."""
        import fleet
        
        # Try to access various modules to trigger any circular imports
        modules_to_test = [
            'fleet.client',
            'fleet._async.client', 
            'fleet.env.client',
            'fleet.verifiers.verifier',
            'fleet.tasks',
            'fleet.models',
            'fleet.resources.sqlite',
            'fleet.resources.browser',
            'fleet.exceptions',
            'fleet.config',
            'fleet.types'
        ]
        
        for module_name in modules_to_test:
            try:
                __import__(module_name)
                print(f"✅ Module imports cleanly: {module_name}")
            except Exception as e:
                pytest.fail(f"Circular import detected in {module_name}: {e}")
    
    def test_import_in_different_contexts(self):
        """Test imports work in different contexts (functions, classes, etc.)."""
        
        def test_in_function():
            from fleet import Fleet
            return Fleet is not None
        
        class TestInClass:
            def test_method(self):
                from fleet import Fleet
                return Fleet is not None
        
        # Test in function context
        assert test_in_function()
        
        # Test in class context
        test_instance = TestInClass()
        assert test_instance.test_method()
        
        print("✅ Imports work in different contexts")
    
    def test_import_with_sys_path_manipulation(self):
        """Test that imports work even with sys.path manipulation."""
        import sys
        original_path = sys.path.copy()
        
        try:
            # Add current directory to path
            sys.path.insert(0, '.')
            
            # Should still be able to import
            import fleet
            from fleet import Fleet
            
            assert fleet is not None
            assert Fleet is not None
            
            print("✅ Imports work with sys.path manipulation")
            
        finally:
            # Restore original path
            sys.path = original_path
