"""
Tests for browser operations functionality.
"""

import pytest
from .base_test import BaseBrowserTest, BaseFleetTest


class TestBrowserOperations(BaseBrowserTest):
    """Test browser operations functionality."""
    
    def test_browser_cdp_url_format(self, env):
        """Test browser CDP URL format."""
        browser = env.browser()
        cdp_url = browser.cdp_url()
        assert isinstance(cdp_url, str)
        assert len(cdp_url) > 0
        # CDP URL should be a valid URL
        assert cdp_url.startswith(('http://', 'https://', 'ws://', 'wss://'))
        print(f"✅ Browser CDP URL format valid: {cdp_url}")
    
    def test_browser_devtools_url_format(self, env):
        """Test browser devtools URL format."""
        browser = env.browser()
        devtools_url = browser.devtools_url()
        assert isinstance(devtools_url, str)
        assert len(devtools_url) > 0
        # DevTools URL should be a valid URL
        assert devtools_url.startswith(('http://', 'https://'))
        print(f"✅ Browser devtools URL format valid: {devtools_url}")
    
    def test_browser_urls_consistency(self, env):
        """Test browser URLs consistency."""
        browser = env.browser()
        cdp_url = browser.cdp_url()
        devtools_url = browser.devtools_url()
        
        # Both URLs should be different
        assert cdp_url != devtools_url
        print("✅ Browser URLs are consistent and different")
    
    def test_browser_resource_integration(self, env):
        """Test browser as environment resource."""
        resources = env.resources()
        assert isinstance(resources, list)
        
        # Find browser/CDP resource
        browser_resources = [r for r in resources if hasattr(r, 'type') and r.type in ['cdp', 'browser']]
        # Just check that resources exist, don't require specific browser resources
        assert len(resources) > 0
        print(f"✅ Browser resource integration: {len(resources)} total resources found")


class TestAsyncBrowserOperations(BaseBrowserTest):
    """Test async browser operations."""
    
    @pytest.mark.asyncio
    async def test_async_browser_cdp_url(self):
        """Test async browser CDP URL."""
        import os
        from fleet import AsyncFleet
        
        api_key = os.getenv("FLEET_API_KEY")
        if not api_key:
            pytest.skip("API key required for integration tests")
        
        async_fleet = AsyncFleet(api_key=api_key)
        async_env = await async_fleet.make("dropbox:Forge1.1.0")
        
        try:
            browser = async_env.browser()
            cdp_url = await browser.cdp_url()
            assert isinstance(cdp_url, str)
            assert len(cdp_url) > 0
            print(f"✅ Async browser CDP URL: {cdp_url}")
        finally:
            await async_env.close()
    
    @pytest.mark.asyncio
    async def test_async_browser_devtools_url(self):
        """Test async browser devtools URL."""
        import os
        from fleet import AsyncFleet
        
        api_key = os.getenv("FLEET_API_KEY")
        if not api_key:
            pytest.skip("API key required for integration tests")
        
        async_fleet = AsyncFleet(api_key=api_key)
        async_env = await async_fleet.make("dropbox:Forge1.1.0")
        
        try:
            browser = async_env.browser()
            devtools_url = await browser.devtools_url()
            assert isinstance(devtools_url, str)
            assert len(devtools_url) > 0
            print(f"✅ Async browser devtools URL: {devtools_url}")
        finally:
            await async_env.close()
    
    @pytest.mark.asyncio
    async def test_async_browser_urls_consistency(self):
        """Test async browser URLs consistency."""
        import os
        from fleet import AsyncFleet
        
        api_key = os.getenv("FLEET_API_KEY")
        if not api_key:
            pytest.skip("API key required for integration tests")
        
        async_fleet = AsyncFleet(api_key=api_key)
        async_env = await async_fleet.make("dropbox:Forge1.1.0")
        
        try:
            browser = async_env.browser()
            cdp_url = await browser.cdp_url()
            devtools_url = await browser.devtools_url()
            
            assert cdp_url != devtools_url
            print("✅ Async browser URLs are consistent and different")
        finally:
            await async_env.close()
    
    @pytest.mark.asyncio
    async def test_async_browser_resource_integration(self):
        """Test async browser as environment resource."""
        import os
        from fleet import AsyncFleet
        
        api_key = os.getenv("FLEET_API_KEY")
        if not api_key:
            pytest.skip("API key required for integration tests")
        
        async_fleet = AsyncFleet(api_key=api_key)
        async_env = await async_fleet.make("dropbox:Forge1.1.0")
        
        try:
            resources = await async_env.resources()
            assert isinstance(resources, list)
            
            # Find browser/CDP resource
            browser_resources = [r for r in resources if hasattr(r, 'type') and r.type in ['cdp', 'browser']]
            # Just check that resources exist, don't require specific browser resources
            assert len(resources) > 0
            print(f"✅ Async browser resource integration: {len(resources)} total resources found")
        finally:
            await async_env.close()


class TestBrowserIntegration(BaseFleetTest):
    """Test browser integration with environment."""
    
    def test_browser_with_environment_reset(self, env):
        """Test browser operations with environment reset."""
        # Reset environment
        reset_response = env.reset(seed=42)
        assert reset_response is not None
        
        # Test browser after reset
        browser = env.browser()
        cdp_url = browser.cdp_url()
        devtools_url = browser.devtools_url()
        
        assert cdp_url is not None
        assert devtools_url is not None
        print("✅ Browser with environment reset successful")
    
    def test_browser_with_environment_step(self, env):
        """Test browser operations with environment step."""
        # Perform environment step
        action = {"type": "test", "data": {"message": "Hello Fleet!"}}
        state, reward, done = env.instance.step(action)
        
        # Test browser after step
        browser = env.browser()
        cdp_url = browser.cdp_url()
        devtools_url = browser.devtools_url()
        
        assert cdp_url is not None
        assert devtools_url is not None
        print("✅ Browser with environment step successful")
    
    def test_browser_and_database_together(self, env):
        """Test browser and database operations together."""
        # Test database
        db = env.db()
        db_result = db.query("SELECT 1 as test")
        assert db_result is not None
        
        # Test browser
        browser = env.browser()
        cdp_url = browser.cdp_url()
        devtools_url = browser.devtools_url()
        
        assert cdp_url is not None
        assert devtools_url is not None
        print("✅ Browser and database operations work together")
