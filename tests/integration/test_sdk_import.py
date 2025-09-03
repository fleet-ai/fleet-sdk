import pytest
from .base_test import BaseFleetTest


@pytest.mark.integration
class TestSDKImport(BaseFleetTest):
    """Test that SDK can be imported and used as packaged."""
    
    def test_import_main_modules(self):
        """Test that all main SDK modules can be imported."""
        # Test main sync imports
        import fleet
        from fleet import Fleet, SyncEnv
        from fleet.tasks import Task
        
        # Verify classes are available
        assert hasattr(fleet, 'Fleet'), "Fleet should be importable from fleet"
        assert hasattr(fleet, 'SyncEnv'), "SyncEnv should be importable from fleet"
        assert Fleet is not None, "Fleet class should be available"
        assert SyncEnv is not None, "SyncEnv class should be available"
        assert Task is not None, "Task class should be available"
    
    def test_import_async_modules(self):
        """Test that async SDK modules can be imported."""
        # Test async imports  
        from fleet import AsyncFleet, AsyncEnv
        from fleet._async.tasks import Task as AsyncTask
        
        # Verify async classes are available
        assert AsyncFleet is not None, "AsyncFleet class should be available"
        assert AsyncEnv is not None, "AsyncEnv class should be available"
        assert AsyncTask is not None, "AsyncTask class should be available"
    
    def test_import_resources(self):
        """Test that resource modules can be imported."""
        from fleet.resources.sqlite import SQLiteResource
        from fleet.resources.browser import BrowserResource
        from fleet._async.resources.sqlite import AsyncSQLiteResource
        from fleet._async.resources.browser import AsyncBrowserResource
        
        assert SQLiteResource is not None, "SQLiteResource should be importable"
        assert BrowserResource is not None, "BrowserResource should be importable"
        assert AsyncSQLiteResource is not None, "AsyncSQLiteResource should be importable"
        assert AsyncBrowserResource is not None, "AsyncBrowserResource should be importable"
    
    def test_import_verifiers(self):
        """Test that verifier modules can be imported."""
        # Import the decorator function directly (not the module)
        from fleet.verifiers.decorator import verifier
        from fleet._async.verifiers.verifier import verifier as async_verifier
        
        # Both decorators should be callable functions
        assert callable(verifier), "verifier should be callable"
        assert callable(async_verifier), "async verifier should be callable"
        
        # Test basic verifier usage (call as decorator factory)
        @verifier()
        def test_verifier(env):
            return {"score": 1.0, "message": "Test passed"}
        
        assert test_verifier is not None, "decorated verifier should work"
    
    def test_client_initialization(self, api_key):
        """Test that Fleet client can be initialized."""
        from fleet import Fleet
        
        # Test valid initialization
        client = Fleet(api_key=api_key)
        self.assert_fleet_client(client)
    
    def test_async_client_initialization(self, api_key):
        """Test that AsyncFleet client can be initialized."""
        from fleet import AsyncFleet
        
        # Test valid async initialization
        client = AsyncFleet(api_key=api_key)
        self.assert_async_fleet_client(client)
    
    def test_invalid_api_key_handling(self):
        """Test that invalid API keys are handled properly."""
        from fleet import Fleet
        import os
        
        # Fleet DOES validate API key during initialization
        # Test None API key when no env var is set
        old_key = os.environ.get('FLEET_API_KEY')
        if 'FLEET_API_KEY' in os.environ:
            del os.environ['FLEET_API_KEY']
        
        try:
            with pytest.raises(ValueError, match="api_key is required"):
                Fleet(api_key=None)
            
            # Test empty API key - Fleet actually accepts empty strings
            client_empty = Fleet(api_key="")
            assert client_empty is not None, "Client with empty API key should be created"
        finally:
            # Restore environment
            if old_key is not None:
                os.environ['FLEET_API_KEY'] = old_key
    
    def test_global_client_functions(self, api_key):
        """Test global client configuration functions."""
        import fleet
        
        # Test configure function
        fleet.configure(api_key=api_key)
        
        # Test get_client function
        client = fleet.get_client()
        assert client is not None, "get_client() should return a client"
        self.assert_fleet_client(client)
        
        # Test reset_client function
        fleet.reset_client()
        
        # Get client again after reset
        new_client = fleet.get_client()
        assert new_client is not client, "Should get new client after reset"
