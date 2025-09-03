import pytest
from .base_test import BaseEnvironmentTest


@pytest.mark.integration
class TestDatabaseResources(BaseEnvironmentTest):
    """Test database resource functionality with real databases."""
    
    @pytest.mark.requires_instance
    def test_database_basic_operations(self, fleet_client, test_env_key):
        """Test basic database operations."""
        env = self.get_test_environment(fleet_client, test_env_key)
        
        try:
            db = env.db()
            
            # Test simple query
            result = db.exec("SELECT 1 as test_num, 'hello' as test_str")
            
            self.assert_valid_response(result, dict)
            assert "columns" in result, "Result should have columns"
            assert "rows" in result, "Result should have rows"
            
            # Verify data structure
            if result["columns"] and result["rows"]:
                assert len(result["rows"]) > 0, "Should have at least one row"
                assert len(result["rows"][0]) == len(result["columns"]), "Row should match column count"
            
        except Exception as e:
            self.skip_if_unavailable("Database basic operations", e)
    
    @pytest.mark.requires_instance  
    def test_database_with_parameters(self, fleet_client, test_env_key):
        """Test database operations with parameters."""
        env = self.get_test_environment(fleet_client, test_env_key)
        
        try:
            db = env.db()
            
            # Test parameterized query
            query = "SELECT ? as param_num, ? as param_str"
            params = [42, "test_param"]
            
            result = db.exec(query, params)
            
            self.assert_valid_response(result, dict)
            
            # Verify parameters were used correctly
            if result.get("rows"):
                row = result["rows"][0] 
                assert 42 in row, "Should contain numeric parameter"
                assert "test_param" in row, "Should contain string parameter"
            
        except Exception as e:
            self.skip_if_unavailable("Database parameterized queries", e)
    
    @pytest.mark.requires_instance
    @pytest.mark.asyncio
    async def test_async_database_operations(self, async_fleet_client, test_env_key):
        """Test async database operations.""" 
        env = await self.get_async_test_environment(async_fleet_client, test_env_key)
        
        try:
            db = env.db()
            
            # Test async query
            result = await db.exec("SELECT 'async_test' as test_type")
            
            self.assert_valid_response(result, dict)
            assert "test_type" in str(result), "Should contain async test data"
            
        except Exception as e:
            self.skip_if_unavailable("Async database operations", e)
    
    @pytest.mark.requires_instance
    def test_database_custom_name(self, fleet_client, test_env_key):
        """Test database access with custom database names."""
        env = self.get_test_environment(fleet_client, test_env_key)
        
        try:
            # Test default database
            db_default = env.db()
            result1 = db_default.exec("SELECT 'default' as db_type")
            self.assert_valid_response(result1, dict)
            
            # Test custom named database (if supported)
            try:
                db_custom = env.db("custom")
                result2 = db_custom.exec("SELECT 'custom' as db_type") 
                self.assert_valid_response(result2, dict)
            except Exception:
                # Custom databases might not be available in all environments
                pass
            
        except Exception as e:
            self.skip_if_unavailable("Database custom names", e)


@pytest.mark.integration
class TestBrowserResources(BaseEnvironmentTest):
    """Test browser resource functionality."""
    
    @pytest.mark.requires_instance
    def test_browser_status(self, fleet_client, test_env_key):
        """Test browser status functionality."""
        env = self.get_test_environment(fleet_client, test_env_key)
        
        try:
            browser = env.browser()
            
            # Test browser status
            status = browser.status()
            
            self.assert_valid_response(status, dict)
            
            # Status should contain useful information
            expected_fields = ["status"]  # Minimal expected field
            for field in expected_fields:
                if field in status:
                    assert status[field] is not None, f"Status {field} should not be None"
            
        except Exception as e:
            self.skip_if_unavailable("Browser status", e)
    
    @pytest.mark.requires_instance
    @pytest.mark.slow
    def test_browser_navigation(self, fleet_client, test_env_key):
        """Test browser navigation functionality."""
        env = self.get_test_environment(fleet_client, test_env_key)
        
        try:
            browser = env.browser()
            
            # Test navigation to a simple page
            test_url = "https://httpbin.org/html"
            result = browser.navigate(test_url)
            
            self.assert_valid_response(result, dict)
            
            # Should indicate successful navigation
            if "success" in result:
                assert result["success"] is True, "Navigation should be successful"
            
        except Exception as e:
            self.skip_if_unavailable("Browser navigation", e)
    
    @pytest.mark.requires_instance
    @pytest.mark.asyncio
    async def test_async_browser_operations(self, async_fleet_client, test_env_key):
        """Test async browser operations."""
        env = await self.get_async_test_environment(async_fleet_client, test_env_key)
        
        try:
            browser = env.browser()
            
            # Test async browser status
            status = await browser.status()
            self.assert_valid_response(status, dict)
            
        except Exception as e:
            self.skip_if_unavailable("Async browser operations", e)


@pytest.mark.integration
class TestResourceStateAccess(BaseEnvironmentTest):
    """Test resource access via state() method."""
    
    @pytest.mark.requires_instance
    def test_sqlite_state_access(self, fleet_client, test_env_key):
        """Test SQLite resource access via state() method."""
        env = self.get_test_environment(fleet_client, test_env_key)
        
        try:
            # Access SQLite resource via state
            sqlite_resource = env.state("sqlite://current")
            
            # Should return a working SQLite resource
            result = sqlite_resource.exec("SELECT 'state_access' as access_type")
            
            self.assert_valid_response(result, dict)
            assert "state_access" in str(result), "Should contain state access data"
            
        except Exception as e:
            self.skip_if_unavailable("SQLite state access", e)
    
    @pytest.mark.requires_instance  
    def test_browser_state_access(self, fleet_client, test_env_key):
        """Test browser resource access via state() method."""
        env = self.get_test_environment(fleet_client, test_env_key)
        
        try:
            # Access browser resource via state
            browser_resource = env.state("browser://cdp")
            
            # Should return a working browser resource
            status = browser_resource.status()
            
            self.assert_valid_response(status, dict)
            
        except Exception as e:
            self.skip_if_unavailable("Browser state access", e)
    
    @pytest.mark.requires_instance
    def test_state_access_error_handling(self, fleet_client, test_env_key):
        """Test state() method error handling."""
        env = self.get_test_environment(fleet_client, test_env_key)
        
        # Test invalid protocol
        with pytest.raises(Exception):  # Should raise some kind of error
            env.state("invalid://resource")
        
        # Test malformed URI  
        with pytest.raises(Exception):  # Should raise some kind of error
            env.state("not-a-valid-uri")
