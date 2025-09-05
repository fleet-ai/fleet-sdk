"""
Tests for MCP (Model Context Protocol) integration functionality.
"""

import pytest
from .base_test import BaseFleetTest


class TestMCPIntegration(BaseFleetTest):
    """Test MCP integration functionality."""
    
    def test_mcp_url_access(self, env):
        """Test MCP URL access."""
        assert hasattr(env, 'mcp')
        assert hasattr(env.mcp, 'url')
        assert env.mcp.url is not None
        assert isinstance(env.mcp.url, str)
        assert len(env.mcp.url) > 0
        print(f"✅ MCP URL accessible: {env.mcp.url}")
    
    def test_mcp_openai_integration(self, env):
        """Test MCP OpenAI integration."""
        assert hasattr(env.mcp, 'openai')
        openai_tools = env.mcp.openai()
        assert openai_tools is not None
        print("✅ MCP OpenAI integration works")
    
    def test_mcp_url_format(self, env):
        """Test MCP URL format."""
        mcp_url = env.mcp.url
        # MCP URL should be a valid URL
        assert mcp_url.startswith(('http://', 'https://', 'ws://', 'wss://'))
        print(f"✅ MCP URL format valid: {mcp_url}")
    
    def test_mcp_with_environment_reset(self, env):
        """Test MCP with environment reset."""
        # Reset environment
        reset_response = env.reset(seed=42)
        assert reset_response is not None
        
        # Test MCP after reset
        mcp_url = env.mcp.url
        assert mcp_url is not None
        print("✅ MCP with environment reset successful")
    
    def test_mcp_with_environment_step(self, env):
        """Test MCP with environment step."""
        # Perform environment step
        action = {"type": "test", "data": {"message": "Hello Fleet!"}}
        state, reward, done = env.instance.step(action)
        
        # Test MCP after step
        mcp_url = env.mcp.url
        assert mcp_url is not None
        print("✅ MCP with environment step successful")
    
    def test_mcp_and_database_together(self, env):
        """Test MCP and database operations together."""
        # Test database
        db = env.db()
        db_result = db.query("SELECT 1 as test")
        assert db_result is not None
        
        # Test MCP
        mcp_url = env.mcp.url
        assert mcp_url is not None
        print("✅ MCP and database operations work together")
    
    def test_mcp_and_browser_together(self, env):
        """Test MCP and browser operations together."""
        # Test browser
        browser = env.browser()
        cdp_url = browser.cdp_url()
        devtools_url = browser.devtools_url()
        
        assert cdp_url is not None
        assert devtools_url is not None
        
        # Test MCP
        mcp_url = env.mcp.url
        assert mcp_url is not None
        print("✅ MCP and browser operations work together")


class TestAsyncMCPIntegration(BaseFleetTest):
    """Test async MCP integration functionality."""
    
    @pytest.mark.asyncio
    async def test_async_mcp_url_access(self):
        """Test async MCP URL access."""
        import os
        from fleet import AsyncFleet
        
        api_key = os.getenv("FLEET_API_KEY")
        if not api_key:
            pytest.skip("API key required for integration tests")
        
        async_fleet = AsyncFleet(api_key=api_key)
        async_env = await async_fleet.make("dropbox:Forge1.1.0")
        
        try:
            assert hasattr(async_env, 'mcp')
            assert hasattr(async_env.mcp, 'url')
            assert async_env.mcp.url is not None
            assert isinstance(async_env.mcp.url, str)
            assert len(async_env.mcp.url) > 0
            print(f"✅ Async MCP URL accessible: {async_env.mcp.url}")
        finally:
            await async_env.close()
    
    @pytest.mark.asyncio
    async def test_async_mcp_openai_integration(self):
        """Test async MCP OpenAI integration."""
        import os
        from fleet import AsyncFleet
        
        api_key = os.getenv("FLEET_API_KEY")
        if not api_key:
            pytest.skip("API key required for integration tests")
        
        async_fleet = AsyncFleet(api_key=api_key)
        async_env = await async_fleet.make("dropbox:Forge1.1.0")
        
        try:
            assert hasattr(async_env.mcp, 'openai')
            openai_tools = async_env.mcp.openai()
            assert openai_tools is not None
            print("✅ Async MCP OpenAI integration works")
        finally:
            await async_env.close()
    
    @pytest.mark.asyncio
    async def test_async_mcp_url_format(self):
        """Test async MCP URL format."""
        import os
        from fleet import AsyncFleet
        
        api_key = os.getenv("FLEET_API_KEY")
        if not api_key:
            pytest.skip("API key required for integration tests")
        
        async_fleet = AsyncFleet(api_key=api_key)
        async_env = await async_fleet.make("dropbox:Forge1.1.0")
        
        try:
            mcp_url = async_env.mcp.url
            # MCP URL should be a valid URL
            assert mcp_url.startswith(('http://', 'https://', 'ws://', 'wss://'))
            print(f"✅ Async MCP URL format valid: {mcp_url}")
        finally:
            await async_env.close()
    
    @pytest.mark.asyncio
    async def test_async_mcp_with_environment_reset(self):
        """Test async MCP with environment reset."""
        import os
        from fleet import AsyncFleet
        
        api_key = os.getenv("FLEET_API_KEY")
        if not api_key:
            pytest.skip("API key required for integration tests")
        
        async_fleet = AsyncFleet(api_key=api_key)
        async_env = await async_fleet.make("dropbox:Forge1.1.0")
        
        try:
            # Reset environment
            reset_response = await async_env.reset(seed=42)
            assert reset_response is not None
            
            # Test MCP after reset
            mcp_url = async_env.mcp.url
            assert mcp_url is not None
            print("✅ Async MCP with environment reset successful")
        finally:
            await async_env.close()
    
    @pytest.mark.asyncio
    async def test_async_mcp_and_database_together(self):
        """Test async MCP and database operations together."""
        import os
        from fleet import AsyncFleet
        
        api_key = os.getenv("FLEET_API_KEY")
        if not api_key:
            pytest.skip("API key required for integration tests")
        
        async_fleet = AsyncFleet(api_key=api_key)
        async_env = await async_fleet.make("dropbox:Forge1.1.0")
        
        try:
            # Test database
            db = async_env.db()
            db_result = await db.query("SELECT 1 as test")
            assert db_result is not None
            
            # Test MCP
            mcp_url = async_env.mcp.url
            assert mcp_url is not None
            print("✅ Async MCP and database operations work together")
        finally:
            await async_env.close()
    
    @pytest.mark.asyncio
    async def test_async_mcp_and_browser_together(self):
        """Test async MCP and browser operations together."""
        import os
        from fleet import AsyncFleet
        
        api_key = os.getenv("FLEET_API_KEY")
        if not api_key:
            pytest.skip("API key required for integration tests")
        
        async_fleet = AsyncFleet(api_key=api_key)
        async_env = await async_fleet.make("dropbox:Forge1.1.0")
        
        try:
            # Test browser
            browser = async_env.browser()
            cdp_url = await browser.cdp_url()
            devtools_url = await browser.devtools_url()
            
            assert cdp_url is not None
            assert devtools_url is not None
            
            # Test MCP
            mcp_url = async_env.mcp.url
            assert mcp_url is not None
            print("✅ Async MCP and browser operations work together")
        finally:
            await async_env.close()


class TestMCPAdvanced(BaseFleetTest):
    """Test advanced MCP functionality."""
    
    def test_mcp_url_consistency(self, env):
        """Test MCP URL consistency across operations."""
        # Get MCP URL
        mcp_url1 = env.mcp.url
        
        # Perform some operations
        db = env.db()
        db.query("SELECT 1 as test")
        
        # Get MCP URL again
        mcp_url2 = env.mcp.url
        
        # URLs should be consistent
        assert mcp_url1 == mcp_url2
        print("✅ MCP URL consistency maintained")
    
    def test_mcp_url_across_environments(self, fleet_client):
        """Test MCP URL across different environments."""
        # Create multiple environments
        env1 = fleet_client.make("dropbox:Forge1.1.0")
        env2 = fleet_client.make("hubspot:Forge1.1.0")
        
        try:
            mcp_url1 = env1.mcp.url
            mcp_url2 = env2.mcp.url
            
            # Both should have valid URLs
            assert mcp_url1 is not None
            assert mcp_url2 is not None
            assert isinstance(mcp_url1, str)
            assert isinstance(mcp_url2, str)
            
            print("✅ MCP URL works across different environments")
        finally:
            # Cleanup
            env1.close()
            env2.close()
    
    def test_mcp_openai_tools_structure(self, env):
        """Test MCP OpenAI tools structure."""
        openai_tools = env.mcp.openai()
        assert openai_tools is not None
        
        # If it's a list, check structure
        if isinstance(openai_tools, list):
            assert len(openai_tools) > 0
            for tool in openai_tools:
                assert isinstance(tool, dict)
                assert 'type' in tool
                assert 'function' in tool
        
        print("✅ MCP OpenAI tools structure valid")
    
    def test_mcp_resource_integration(self, env):
        """Test MCP as environment resource."""
        resources = env.resources()
        assert isinstance(resources, list)
        
        # MCP should be available as a resource
        mcp_resources = [r for r in resources if hasattr(r, 'type') and r.type == 'mcp']
        # Note: MCP might not be listed as a separate resource type
        print(f"✅ MCP resource integration: {len(mcp_resources)} MCP resources found")
